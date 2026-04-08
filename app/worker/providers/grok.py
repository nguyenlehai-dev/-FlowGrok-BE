from __future__ import annotations

from pathlib import Path
from urllib.request import urlopen

from app.services.playwright_runtime import (
    build_browser_context_kwargs,
    build_browser_launch_kwargs,
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
        self._page = None
        self._boot_state: dict[str, object] = {}

    def bootstrap_context(self) -> dict[str, object]:
        super().bootstrap_context()
        try:
            sync_playwright = get_playwright_sync_api()
            self._playwright = sync_playwright().start()
            launch_kwargs = build_browser_launch_kwargs(self.context)
            self._browser = self._playwright.chromium.launch(**launch_kwargs)
            context_kwargs = build_browser_context_kwargs(self.context)
            browser_context = self._browser.new_context(**context_kwargs)
            self._page = browser_context.new_page()
            self._page.set_default_timeout(
                int((self.context.runtime_settings or {}).get("timeout_ms") or 120000)
            )
            self._boot_state = {
                "browser": "chromium",
                "headless": self.context.headless,
                "storage_state_loaded": bool(context_kwargs.get("storage_state")),
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
        page = self._require_page()
        try:
            page.goto("https://grok.com/", wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            title = page.title()
            url = page.url
            body_text = (page.locator("body").inner_text(timeout=5000) or "")[:1200]
            lowered_body = body_text.lower()
            lowered_title = title.lower()
            has_challenge = any(
                marker in lowered_body or marker in lowered_title
                for marker in [
                    "just a moment",
                    "checking your browser",
                    "verify you are human",
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
            looks_logged_in = not has_challenge and not has_login_prompt
            return {
                "provider": self.provider_name,
                "status": "ok" if looks_logged_in else "cookie_needs_review",
                "url": url,
                "title": title,
                "looks_logged_in": looks_logged_in,
                "has_challenge": has_challenge,
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
            if self._browser is not None:
                self._browser.close()
        finally:
            self._browser = None
            self._page = None
            if self._playwright is not None:
                self._playwright.stop()
                self._playwright = None

    def _generate(self, mode: str) -> list[ProviderArtifact]:
        page = self._require_page()
        try:
            page.goto("https://grok.com/", wait_until="domcontentloaded")
            page.wait_for_timeout(2500)

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
