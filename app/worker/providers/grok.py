from __future__ import annotations

import json
from pathlib import Path
from urllib.request import urlopen

from app.services.playwright_runtime import (
    build_browser_init_script,
    build_browser_context_kwargs,
    build_browser_launch_kwargs,
    get_browser_cdp_url,
    get_playwright_sync_api,
)
from app.worker.providers.base import (
    ProviderArtifact,
    ProviderAutomation,
    ProviderAutomationError,
)


class GrokAutomationProvider(ProviderAutomation):
    provider_name = "grok"

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
                f"Failed to bootstrap Playwright context: {exc}",
            ) from exc

    def validate_cookies(self) -> dict[str, object]:
        has_cookie_state = bool(self.context.storage_state_path and Path(self.context.storage_state_path).exists())
        has_normalized_cookie = bool(self.context.normalized_cookie_path and Path(self.context.normalized_cookie_path).exists())
        if not has_cookie_state and not has_normalized_cookie:
            raise ProviderAutomationError(
                "COOKIE_INVALID",
                "Profile does not have a usable Grok storage state or normalized cookie file",
            )
        return {
            "provider": self.provider_name,
            "storage_state_exists": has_cookie_state,
            "normalized_cookie_exists": has_normalized_cookie,
        }

    def login_with_cookies(self) -> dict[str, object]:
        try:
            diagnostics = self._goto_grok()
            prompt_visible = self._find_prompt_input() is not None
            looks_logged_in = prompt_visible or (
                not bool(diagnostics.get("has_challenge"))
                and not bool(diagnostics.get("has_login_prompt"))
            )
            return {
                "provider": self.provider_name,
                "status": "ok" if looks_logged_in else "cookie_needs_review",
                "url": diagnostics.get("url"),
                "title": diagnostics.get("title"),
                "looks_logged_in": looks_logged_in,
                "prompt_visible": prompt_visible,
                "has_challenge": diagnostics.get("has_challenge"),
                "has_login_prompt": diagnostics.get("has_login_prompt"),
                "challenge_wait_ms": diagnostics.get("challenge_wait_ms"),
            }
        except Exception as exc:
            raise ProviderAutomationError(
                "LOGIN_FAILED",
                f"Failed to restore Grok session with cookies: {exc}",
                artifacts=self._collect_debug_artifacts("grok-login-failed"),
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
            diagnostics = self._goto_grok()
            self._raise_for_blocked_session(mode, diagnostics)

            prompt_input = self._find_prompt_input()
            if prompt_input is None:
                raise ProviderAutomationError(
                    "SELECTOR_NOT_FOUND",
                    "Could not locate a Grok prompt input field",
                    artifacts=self._collect_debug_artifacts(f"{mode}-selector-not-found"),
                )

            prompt_input.click()
            prompt_input.fill(self.context.prompt)
            page.wait_for_timeout(400)

            submit_clicked = self._submit_prompt(mode)
            page.wait_for_timeout(8000)

            generated_artifacts = (
                self._collect_generated_video_artifacts()
                if mode == "generate_video"
                else self._collect_generated_image_artifacts()
            )
            if not generated_artifacts:
                raise ProviderAutomationError(
                    "GENERATION_OUTPUT_NOT_FOUND",
                    f"Grok {mode} did not expose a detectable output artifact",
                    artifacts=self._collect_debug_artifacts(f"grok-{mode}-output-not-found"),
                )

            return generated_artifacts + self._collect_debug_artifacts(f"grok-{mode}") + [
                ProviderArtifact(
                    artifact_type="metadata",
                    file_name=f"grok-{mode}.txt",
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
                        "site": "https://grok.com/",
                    },
                ),
            ]
        except ProviderAutomationError:
            raise
        except Exception as exc:
            raise ProviderAutomationError(
                "GENERATION_FAILED",
                f"Grok {mode} execution failed: {exc}",
                artifacts=self._collect_debug_artifacts(f"grok-{mode}-failed"),
            ) from exc

    def _raise_for_blocked_session(self, mode: str, diagnostics: dict[str, object]) -> None:
        has_challenge = bool(diagnostics.get("has_challenge"))
        has_login_prompt = bool(diagnostics.get("has_login_prompt"))
        if not has_challenge and not has_login_prompt:
            return

        blocked_reason = "challenge" if has_challenge else "login_prompt"
        title = str(diagnostics.get("title") or "").strip() or "Unknown page"
        url = str(diagnostics.get("url") or "").strip() or "https://grok.com/"
        wait_ms = int(diagnostics.get("challenge_wait_ms") or 0)
        if has_challenge:
            message = (
                f"Grok browser session is blocked by a security challenge before {mode}. "
                f"title={title!r} url={url} wait_ms={wait_ms}"
            )
            error_code = "CHALLENGE_BLOCKED"
        else:
            message = (
                f"Grok browser session requires manual login before {mode}. "
                f"title={title!r} url={url} wait_ms={wait_ms}"
            )
            error_code = "LOGIN_REQUIRED"

        artifacts = self._collect_debug_artifacts(f"grok-{mode}-{blocked_reason}")
        artifacts.append(
            ProviderArtifact(
                artifact_type="metadata",
                file_name=f"grok-{mode}-{blocked_reason}.txt",
                mime_type="text/plain",
                text_content="\n".join([
                    f"provider={self.provider_name}",
                    f"mode={mode}",
                    f"status={blocked_reason}",
                    f"title={title}",
                    f"url={url}",
                    f"wait_ms={wait_ms}",
                    f"has_challenge={has_challenge}",
                    f"has_login_prompt={has_login_prompt}",
                ]),
                metadata={
                    "provider": self.provider_name,
                    "mode": mode,
                    "blocked_reason": blocked_reason,
                    "url": url,
                },
            )
        )
        raise ProviderAutomationError(error_code, message, artifacts=artifacts)

    def _goto_grok(self) -> dict[str, object]:
        page = self._require_page()
        total_wait_ms = 0
        for index, target_url in enumerate([
            "https://grok.com/",
            "https://grok.com/?source=flowgrok",
            "https://grok.com/i",
        ]):
            page.goto(target_url, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            total_wait_ms += 2500
            state = self._read_page_state()
            if not state["has_challenge"] and not state["has_login_prompt"]:
                state["challenge_wait_ms"] = total_wait_ms
                return state
            if index == 0:
                for wait_ms in [5000, 10000]:
                    page.wait_for_timeout(wait_ms)
                    total_wait_ms += wait_ms
                    state = self._read_page_state()
                    if not state["has_challenge"] and not state["has_login_prompt"]:
                        state["challenge_wait_ms"] = total_wait_ms
                        return state
        state = self._read_page_state()
        state["challenge_wait_ms"] = total_wait_ms
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

    def _load_session_state(self, storage_state_path: str | None) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
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
        body_text = (page.locator("body").inner_text(timeout=5000) or "")[:3000]
        lowered_body = body_text.lower()
        lowered_title = title.lower()
        has_challenge = any(
            marker in lowered_body or marker in lowered_title
            for marker in [
                "just a moment",
                "checking your browser",
                "verify you are human",
                "security verification",
                "performing security verification",
                "cf-browser-verification",
                "cloudflare",
            ]
        )
        has_login_prompt = any(
            marker in lowered_body
            for marker in [
                "sign in",
                "log in",
                "login",
                "continue with x",
            ]
        )
        return {
            "title": title,
            "url": url,
            "body_text": body_text,
            "has_challenge": has_challenge,
            "has_login_prompt": has_login_prompt,
        }

    def _find_prompt_input(self):
        page = self._require_page()
        selector_candidates = [
            'textarea',
            '[contenteditable="true"]',
            '[data-testid="composer-text-input"]',
            'textarea[placeholder*="Ask"]',
            'textarea[placeholder*="message"]',
        ]
        for selector in selector_candidates:
            locator = page.locator(selector).first
            try:
                if locator.is_visible(timeout=1500):
                    return locator
            except Exception:
                continue
        return None

    def _submit_prompt(self, mode: str) -> bool:
        page = self._require_page()
        submit_selectors = [
            'button[aria-label*="Send"]',
            'button[aria-label*="Generate"]',
            'button:has-text("Generate")',
            'button:has-text("Create")',
            'button:has-text("Send")',
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
            'img[alt*="Generated"]',
            'main img',
        ]
        for selector in image_selectors:
            locator = page.locator(selector).first
            try:
                if locator.is_visible(timeout=1500):
                    src = locator.get_attribute("src")
                    return [
                        ProviderArtifact(
                            artifact_type="image",
                            file_name="grok-generated.png",
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
        ]
        for selector in video_selectors:
            locator = page.locator(selector).first
            try:
                if not locator.is_visible(timeout=1500):
                    continue
                src = locator.get_attribute("src")
                if selector == "video" and not src:
                    src = locator.evaluate("node => node.currentSrc || node.src || ''")
                if src and src.startswith(("http://", "https://")):
                    with urlopen(src, timeout=30) as response:
                        payload = response.read()
                    return [
                        ProviderArtifact(
                            artifact_type="video",
                            file_name="grok-generated.mp4",
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
                "Grok provider page is not initialized",
            )
        return self._page

    def _require_browser_context(self):
        if self._browser_context is None:
            raise ProviderAutomationError(
                "PLAYWRIGHT_NOT_BOOTSTRAPPED",
                "Grok provider browser context is not initialized",
            )
        return self._browser_context
