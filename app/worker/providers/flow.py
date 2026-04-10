from __future__ import annotations

import json
from pathlib import Path
from urllib.request import urlopen

from app.services.playwright_runtime import (
    build_browser_context_kwargs,
    build_browser_init_script,
    build_browser_launch_kwargs,
    get_browser_cdp_url,
    get_playwright_sync_api,
)
from app.worker.providers.base import (
    ProviderArtifact,
    ProviderAutomation,
    ProviderAutomationError,
)


class FlowAutomationProvider(ProviderAutomation):
    provider_name = "flow"

    def __init__(self, context):
        super().__init__(context)
        self._playwright = None
        self._browser = None
        self._browser_context = None
        self._page = None
        self._boot_state: dict[str, object] = {}

    def bootstrap_context(self) -> dict[str, object]:
        super().bootstrap_context()
        try:
            sync_playwright = get_playwright_sync_api()
            self._playwright = sync_playwright().start()
            cdp_url = get_browser_cdp_url(self.context)
            if cdp_url:
                self._browser = self._playwright.chromium.connect_over_cdp(cdp_url)
                contexts = self._browser.contexts
                if contexts:
                    self._browser_context = contexts[0]
                else:
                    self._browser_context = self._browser.new_context()
                self._browser_context.add_init_script(build_browser_init_script(self.context))
                pages = self._browser_context.pages
                self._page = pages[0] if pages else self._browser_context.new_page()
                self._boot_state = {
                    "browser": "chromium",
                    "headless": self.context.headless,
                    "persistent_context": True,
                    "cdp_connected": True,
                    "cdp_url": cdp_url,
                }
                return self._boot_state

            launch_kwargs = build_browser_launch_kwargs(self.context)
            context_kwargs = build_browser_context_kwargs(self.context)
            storage_state_path = context_kwargs.pop("storage_state", None)
            browser_dir = Path(self.context.browser_dir)
            browser_dir.mkdir(parents=True, exist_ok=True)
            self._browser_context = self._playwright.chromium.launch_persistent_context(
                str(browser_dir),
                **launch_kwargs,
                **context_kwargs,
            )
            self._browser_context.add_init_script(build_browser_init_script(self.context))
            self._page = self._browser_context.new_page()
            self._hydrate_session_state(storage_state_path)
            self._page.set_default_timeout(
                int((self.context.runtime_settings or {}).get("timeout_ms") or 120000)
            )
            self._page.set_default_navigation_timeout(
                int((self.context.runtime_settings or {}).get("navigation_timeout_ms") or 60000)
            )
            self._boot_state = {
                "browser": "chromium",
                "headless": self.context.headless,
                "persistent_context": True,
                "cdp_connected": False,
                "storage_state_loaded": bool(storage_state_path),
                "browser_dir": str(browser_dir),
            }
            return self._boot_state
        except Exception as exc:
            self.close()
            raise ProviderAutomationError(
                "PLAYWRIGHT_BOOT_FAILED",
                f"Failed to bootstrap Playwright context for Flow: {exc}",
            ) from exc

    def validate_cookies(self) -> dict[str, object]:
        has_cookie_state = bool(
            self.context.storage_state_path and Path(self.context.storage_state_path).exists()
        )
        has_normalized_cookie = bool(
            self.context.normalized_cookie_path and Path(self.context.normalized_cookie_path).exists()
        )
        if not has_cookie_state and not has_normalized_cookie:
            raise ProviderAutomationError(
                "COOKIE_INVALID",
                "Profile does not have a usable Flow storage state or normalized cookie file",
            )
        return {
            "provider": self.provider_name,
            "storage_state_exists": has_cookie_state,
            "normalized_cookie_exists": has_normalized_cookie,
        }

    def login_with_cookies(self) -> dict[str, object]:
        try:
            diagnostics = self._goto_flow()
            prompt_visible = self._find_prompt_input() is not None
            looks_logged_in = prompt_visible or (
                not bool(diagnostics.get("has_login_prompt"))
                and not bool(diagnostics.get("has_access_block"))
            )
            return {
                "provider": self.provider_name,
                "status": "ok" if looks_logged_in else "cookie_needs_review",
                "url": diagnostics.get("url"),
                "title": diagnostics.get("title"),
                "looks_logged_in": looks_logged_in,
                "prompt_visible": prompt_visible,
                "has_login_prompt": diagnostics.get("has_login_prompt"),
                "has_access_block": diagnostics.get("has_access_block"),
                "wait_ms": diagnostics.get("wait_ms"),
            }
        except Exception as exc:
            raise ProviderAutomationError(
                "LOGIN_FAILED",
                f"Failed to restore Flow session with cookies: {exc}",
                artifacts=self._collect_debug_artifacts("flow-login-failed"),
            ) from exc

    def generate_image(self) -> list[ProviderArtifact]:
        return self._generate("generate_image")

    def generate_video(self) -> list[ProviderArtifact]:
        return self._generate("generate_video")

    def close(self) -> None:
        try:
            if self._browser_context is not None:
                self._browser_context.close()
            if self._browser is not None:
                self._browser.close()
        finally:
            self._browser = None
            self._browser_context = None
            self._page = None
            if self._playwright is not None:
                self._playwright.stop()
                self._playwright = None

    def _generate(self, mode: str) -> list[ProviderArtifact]:
        page = self._require_page()
        try:
            self._goto_flow()

            prompt_input = self._find_prompt_input()
            if prompt_input is None:
                raise ProviderAutomationError(
                    "SELECTOR_NOT_FOUND",
                    "Could not locate a Flow prompt input field",
                    artifacts=self._collect_debug_artifacts(f"{mode}-selector-not-found"),
                )

            prompt_input.click()
            try:
                prompt_input.fill(self.context.prompt)
            except Exception:
                prompt_input.evaluate(
                    "(node, value) => { if ('value' in node) { node.value = value; node.dispatchEvent(new Event('input', { bubbles: true })); } }",
                    self.context.prompt,
                )
            page.wait_for_timeout(500)

            submit_clicked = self._submit_prompt()
            self._wait_for_generation(mode)

            generated_artifacts = (
                self._collect_generated_video_artifacts()
                if mode == "generate_video"
                else self._collect_generated_image_artifacts()
            )
            if not generated_artifacts:
                raise ProviderAutomationError(
                    "GENERATION_OUTPUT_NOT_FOUND",
                    f"Flow {mode} did not expose a detectable output artifact",
                    artifacts=self._collect_debug_artifacts(f"flow-{mode}-output-not-found"),
                )

            return generated_artifacts + self._collect_debug_artifacts(f"flow-{mode}") + [
                ProviderArtifact(
                    artifact_type="metadata",
                    file_name=f"flow-{mode}.txt",
                    mime_type="text/plain",
                    text_content="\n".join([
                        f"provider={self.provider_name}",
                        f"mode={mode}",
                        f"prompt={self.context.prompt}",
                        f"submit_clicked={submit_clicked}",
                        f"url={page.url}",
                    ]),
                    metadata={
                        "provider": self.provider_name,
                        "mode": mode,
                        "site": "https://labs.google/fx/tools/flow/",
                    },
                ),
            ]
        except ProviderAutomationError:
            raise
        except Exception as exc:
            raise ProviderAutomationError(
                "GENERATION_FAILED",
                f"Flow {mode} execution failed: {exc}",
                artifacts=self._collect_debug_artifacts(f"flow-{mode}-failed"),
            ) from exc

    def _goto_flow(self) -> dict[str, object]:
        page = self._require_page()
        total_wait_ms = 0
        for target_url in [
            "https://labs.google/fx/tools/flow/",
            "https://labs.google/fx/",
            "https://labs.google/flow/",
        ]:
            try:
                page.goto(target_url, wait_until="domcontentloaded")
            except Exception:
                continue
            for wait_ms in [2500, 5000, 8000]:
                page.wait_for_timeout(wait_ms)
                total_wait_ms += wait_ms
                state = self._read_page_state()
                if not state["has_login_prompt"] and not state["has_access_block"]:
                    state["wait_ms"] = total_wait_ms
                    return state
        state = self._read_page_state()
        state["wait_ms"] = total_wait_ms
        return state

    def _hydrate_session_state(self, storage_state_path: str | None) -> None:
        page = self._require_page()
        browser_context = self._require_browser_context()
        cookies, origins = self._load_session_state(storage_state_path)
        if cookies:
            browser_context.add_cookies(cookies)
        for origin_state in origins:
            origin = str(origin_state.get("origin") or "").strip()
            local_storage_items = origin_state.get("localStorage") or []
            if not origin or not isinstance(local_storage_items, list):
                continue
            try:
                page.goto(origin, wait_until="domcontentloaded")
                page.evaluate(
                    """
                    items => {
                      for (const item of items) {
                        if (!item || !item.name) continue;
                        window.localStorage.setItem(String(item.name), String(item.value ?? ""));
                      }
                    }
                    """,
                    local_storage_items,
                )
            except Exception:
                continue

    def _load_session_state(
        self,
        storage_state_path: str | None,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        cookies: list[dict[str, object]] = []
        origins: list[dict[str, object]] = []

        if storage_state_path and Path(storage_state_path).exists():
            try:
                payload = json.loads(Path(storage_state_path).read_text())
                if isinstance(payload, dict):
                    raw_cookies = payload.get("cookies") or []
                    raw_origins = payload.get("origins") or []
                    if isinstance(raw_cookies, list):
                        cookies.extend([item for item in raw_cookies if isinstance(item, dict)])
                    if isinstance(raw_origins, list):
                        origins.extend([item for item in raw_origins if isinstance(item, dict)])
            except Exception:
                pass

        normalized_cookie_path = self.context.normalized_cookie_path
        if normalized_cookie_path and Path(normalized_cookie_path).exists():
            try:
                payload = json.loads(Path(normalized_cookie_path).read_text())
                if isinstance(payload, list):
                    cookies.extend([item for item in payload if isinstance(item, dict)])
                elif isinstance(payload, dict) and isinstance(payload.get("cookies"), list):
                    cookies.extend([item for item in payload["cookies"] if isinstance(item, dict)])
            except Exception:
                pass

        deduped_cookies: dict[tuple[str, str, str], dict[str, object]] = {}
        for item in cookies:
            name = str(item.get("name") or "").strip()
            domain = str(item.get("domain") or "").strip()
            path = str(item.get("path") or "/").strip() or "/"
            if not name or not domain:
                continue
            deduped_cookies[(name, domain, path)] = item

        return list(deduped_cookies.values()), origins

    def _read_page_state(self) -> dict[str, object]:
        page = self._require_page()
        title = page.title()
        url = page.url
        body_text = (page.locator("body").inner_text(timeout=5000) or "")[:4000]
        lowered_body = body_text.lower()
        lowered_title = title.lower()
        has_login_prompt = any(
            marker in lowered_body or marker in lowered_title
            for marker in [
                "sign in",
                "log in",
                "choose an account",
                "continue to flow",
                "google accounts",
            ]
        )
        has_access_block = any(
            marker in lowered_body or marker in lowered_title
            for marker in [
                "not available",
                "waitlist",
                "unavailable",
                "access denied",
                "verify it is you",
            ]
        )
        return {
            "title": title,
            "url": url,
            "body_text": body_text,
            "has_login_prompt": has_login_prompt,
            "has_access_block": has_access_block,
        }

    def _find_prompt_input(self):
        page = self._require_page()
        selector_candidates = [
            'textarea',
            '[contenteditable="true"]',
            '[aria-label*="prompt" i]',
            '[aria-label*="describe" i]',
            '[placeholder*="prompt" i]',
            '[placeholder*="describe" i]',
            '[placeholder*="scene" i]',
        ]
        for selector in selector_candidates:
            locator = page.locator(selector).first
            try:
                if locator.is_visible(timeout=1500):
                    return locator
            except Exception:
                continue
        return None

    def _submit_prompt(self) -> bool:
        page = self._require_page()
        submit_selectors = [
            'button[aria-label*="generate" i]',
            'button[aria-label*="create" i]',
            'button[aria-label*="run" i]',
            'button:has-text("Generate")',
            'button:has-text("Create")',
            'button:has-text("Run")',
        ]
        for selector in submit_selectors:
            locator = page.locator(selector).first
            try:
                if locator.is_visible(timeout=1000):
                    locator.click()
                    return True
            except Exception:
                continue

        prompt_input = self._find_prompt_input()
        if prompt_input is not None:
            prompt_input.press("Enter")
            return False
        return False

    def _wait_for_generation(self, mode: str) -> None:
        page = self._require_page()
        max_attempts = 15 if mode == "generate_video" else 10
        delay_ms = 4000 if mode == "generate_video" else 2500
        loading_selectors = [
            '[role="progressbar"]',
            'text=/generating/i',
            'text=/creating/i',
            'text=/rendering/i',
        ]
        for _attempt in range(max_attempts):
            if mode == "generate_video" and self._collect_generated_video_artifacts():
                return
            if mode == "generate_image" and self._collect_generated_image_artifacts():
                return
            loading_visible = False
            for selector in loading_selectors:
                locator = page.locator(selector).first
                try:
                    if locator.is_visible(timeout=500):
                        loading_visible = True
                        break
                except Exception:
                    continue
            page.wait_for_timeout(delay_ms if loading_visible else 1500)

    def _collect_debug_artifacts(self, slug: str) -> list[ProviderArtifact]:
        page = self._require_page()
        screenshot = page.screenshot(full_page=True)
        html_snapshot = page.content()
        return [
            ProviderArtifact(
                artifact_type="debug_screenshot",
                file_name=f"{slug}.png",
                mime_type="image/png",
                binary_content=screenshot,
                metadata={
                    "provider": self.provider_name,
                    "kind": "screenshot",
                    "slug": slug,
                    "url": page.url,
                },
            ),
            ProviderArtifact(
                artifact_type="debug_html",
                file_name=f"{slug}.html",
                mime_type="text/html",
                text_content=html_snapshot,
                metadata={
                    "provider": self.provider_name,
                    "kind": "html",
                    "slug": slug,
                    "url": page.url,
                },
            ),
        ]

    def _collect_generated_image_artifacts(self) -> list[ProviderArtifact]:
        page = self._require_page()
        image_selectors = [
            'img[src^="blob:"]',
            'img[src^="https://"]',
            'img[alt*="generated" i]',
            'img[alt*="preview" i]',
            'main img',
        ]
        for selector in image_selectors:
            locator = page.locator(selector).first
            try:
                if locator.is_visible(timeout=1200):
                    src = locator.get_attribute("src")
                    return [
                        ProviderArtifact(
                            artifact_type="image",
                            file_name="flow-generated.png",
                            mime_type="image/png",
                            binary_content=locator.screenshot(),
                            metadata={
                                "provider": self.provider_name,
                                "selector": selector,
                                "src": src,
                            },
                        )
                    ]
            except Exception:
                continue
        return []

    def _collect_generated_video_artifacts(self) -> list[ProviderArtifact]:
        page = self._require_page()
        video_selectors = [
            'video',
            'video source',
            'a[href$=".mp4"]',
            'a[href*=".mp4?"]',
            'a[href$=".webm"]',
        ]
        for selector in video_selectors:
            locator = page.locator(selector).first
            try:
                if not locator.is_visible(timeout=1200):
                    continue
                src = locator.get_attribute("src") or locator.get_attribute("href")
                if selector == "video" and not src:
                    src = locator.evaluate("node => node.currentSrc || node.src || ''")
                if src and src.startswith(("http://", "https://")):
                    with urlopen(src, timeout=60) as response:
                        payload = response.read()
                    return [
                        ProviderArtifact(
                            artifact_type="video",
                            file_name="flow-generated.mp4",
                            mime_type="video/mp4",
                            binary_content=payload,
                            metadata={
                                "provider": self.provider_name,
                                "selector": selector,
                                "src": src,
                            },
                        )
                    ]
            except Exception:
                continue
        return []

    def _require_page(self):
        if self._page is None:
            raise ProviderAutomationError(
                "PLAYWRIGHT_NOT_BOOTSTRAPPED",
                "Flow provider page is not initialized",
            )
        return self._page

    def _require_browser_context(self):
        if self._browser_context is None:
            raise ProviderAutomationError(
                "PLAYWRIGHT_NOT_BOOTSTRAPPED",
                "Flow provider browser context is not initialized",
            )
        return self._browser_context
