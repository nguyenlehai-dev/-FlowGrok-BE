from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import time
from pathlib import Path

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
        self._captured_video_urls: list[str] = []

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
                self._page = self._select_cdp_page(pages)
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
            self._append_job_debug_log(f"generate: start mode={mode}")
            # Set up network listener to capture video URLs early
            if mode == "generate_video":
                self._captured_video_urls = []
                def _on_response(response):
                    url = response.url
                    content_type = response.headers.get("content-type", "")
                    if (
                        url.endswith(".mp4")
                        or "video/mp4" in content_type
                        or "video/" in content_type
                    ):
                        if url not in self._captured_video_urls:
                            self._captured_video_urls.append(url)
                page.on("response", _on_response)

            diagnostics = self._goto_grok()
            self._append_job_debug_log(
                f"generate: goto_done url={diagnostics.get('url')} title={diagnostics.get('title')}"
            )
            self._raise_for_blocked_session(mode, diagnostics)
            self._open_generation_surface(mode)
            self._append_job_debug_log(f"generate: surface_ready url={page.url}")

            # Dismiss any overlays that may block interaction
            self._dismiss_overlays()
            self._append_job_debug_log("generate: overlays_dismissed")

            prompt_input = self._find_prompt_input()
            if prompt_input is None:
                self._append_job_debug_log("generate: prompt_input_not_found")
                raise ProviderAutomationError(
                    "SELECTOR_NOT_FOUND",
                    "Could not locate a Grok prompt input field",
                    artifacts=self._collect_debug_artifacts(f"{mode}-selector-not-found"),
                )

            prompt_input.click()
            self._append_job_debug_log("generate: prompt_clicked_before_upload")
            self._upload_source_image_if_present()
            self._append_job_debug_log("generate: source_image_step_done")
            if mode == "generate_video":
                self._ensure_video_mode_selected()
            prompt_input = self._find_prompt_input() or prompt_input
            effective_prompt = self._effective_prompt_for_mode(mode)
            prompt_input.click()
            prompt_input.fill(effective_prompt)
            self._append_job_debug_log(f"generate: prompt_filled chars={len(effective_prompt)}")
            page.wait_for_timeout(400)

            submit_clicked = self._submit_prompt(mode)
            self._append_job_debug_log(f"generate: submit_done clicked={submit_clicked} url={page.url}")
            page.wait_for_timeout(8000)

            if mode == "generate_video":
                generated_artifacts = self._collect_generated_video_artifacts()
            else:
                generated_artifacts = self._collect_generated_image_artifacts()
                generated_artifacts.extend(self._collect_current_page_video_artifacts())
            self._append_job_debug_log(f"generate: collect_done artifact_count={len(generated_artifacts)}")
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

    def _select_cdp_page(self, pages):
        for page in pages:
            try:
                if "grok.com" in (page.url or ""):
                    return page
            except Exception:
                continue
        return self._browser_context.new_page()

    def _open_generation_surface(self, mode: str) -> None:
        page = self._require_page()
        try:
            page.goto("https://grok.com/imagine", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)
        except Exception as exc:
            raise ProviderAutomationError(
                "GENERATION_SURFACE_FAILED",
                f"Could not open Grok Imagine surface for video generation: {exc}",
                artifacts=self._collect_debug_artifacts("grok-generate_video-surface-failed"),
            ) from exc

        state = self._read_page_state()
        self._raise_for_blocked_session(mode, state)

        # Switch to Video mode — Grok defaults to Image mode on /imagine
        if mode == "generate_image":
            self._dismiss_overlays()
            image_selectors = [
                'button:has-text("Image")',
                'button[aria-label="Image"]',
                '[role="button"]:has-text("Image")',
            ]
            for selector in image_selectors:
                try:
                    btn = page.locator(selector).first
                    if btn.is_visible(timeout=2000):
                        btn.click()
                        page.wait_for_timeout(1000)
                        break
                except Exception:
                    continue
            return

        video_mode_clicked = False
        video_selectors = [
            'button:has-text("Video")',
            'button[aria-label="Video"]',
            '[role="button"]:has-text("Video")',
        ]
        for selector in video_selectors:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=3000):
                    btn.click()
                    video_mode_clicked = True
                    page.wait_for_timeout(2000)
                    break
            except Exception:
                continue
        if not video_mode_clicked:
            raise ProviderAutomationError(
                "VIDEO_MODE_SWITCH_FAILED",
                "Could not find or click the Video mode button on Grok Imagine",
                artifacts=self._collect_debug_artifacts("grok-generate_video-mode-switch-failed"),
            )

        # Select video options (resolution, duration) from request_payload
        self._select_video_options()

        # Dismiss any modal dialog/overlay that may appear after switching to Video mode
        self._dismiss_overlays()

    def _effective_prompt_for_mode(self, mode: str) -> str:
        prompt = str(self.context.prompt or "")
        if prompt.strip():
            return prompt
        source_image = self.context.request_payload.get("source_image") if self.context.request_payload else None
        if mode == "generate_video" and isinstance(source_image, dict):
            return "Animate this image."
        return prompt

    def _ensure_video_mode_selected(self) -> bool:
        page = self._require_page()
        clicked = False
        selectors = [
            'button:has-text("Video")',
            'button[aria-label="Video"]',
            '[role="button"]:has-text("Video")',
        ]
        for selector in selectors:
            try:
                locator = page.locator(selector)
                count = locator.count()
            except Exception:
                continue
            for index in range(count - 1, -1, -1):
                button = locator.nth(index)
                try:
                    if not button.is_visible(timeout=1000):
                        continue
                    classes = str(button.get_attribute("class") or "").lower()
                    aria_pressed = str(button.get_attribute("aria-pressed") or "").lower()
                    if aria_pressed == "true" or "bg-primary" in classes or "selected" in classes:
                        clicked = True
                        break
                    button.click(timeout=2000)
                    page.wait_for_timeout(1000)
                    clicked = True
                    break
                except Exception:
                    continue
            if clicked:
                break
        if clicked:
            self._select_video_options()
            self._append_job_debug_log("generate: video_mode_ensured_after_upload")
        else:
            self._append_job_debug_log("generate: video_mode_ensure_failed_after_upload")
        return clicked

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
        last_navigation_error = ""
        for index, target_url in enumerate([
            "https://grok.com/",
            "https://grok.com/?source=flowgrok",
            "https://grok.com/i",
        ]):
            try:
                page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
            except Exception as exc:
                last_navigation_error = str(exc)
            page.wait_for_timeout(2500)
            total_wait_ms += 2500
            state = self._read_page_state()
            if not state["has_challenge"] and not state["has_login_prompt"]:
                state["challenge_wait_ms"] = total_wait_ms
                if last_navigation_error:
                    state["last_navigation_error"] = last_navigation_error
                return state
            if index == 0:
                for wait_ms in [3000, 5000]:
                    page.wait_for_timeout(wait_ms)
                    total_wait_ms += wait_ms
                    state = self._read_page_state()
                    if not state["has_challenge"] and not state["has_login_prompt"]:
                        state["challenge_wait_ms"] = total_wait_ms
                        if last_navigation_error:
                            state["last_navigation_error"] = last_navigation_error
                        return state
        state = self._read_page_state()
        state["challenge_wait_ms"] = total_wait_ms
        if last_navigation_error:
            state["last_navigation_error"] = last_navigation_error
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
        try:
            title = page.title()
        except Exception:
            title = ""
        try:
            url = page.url
        except Exception:
            url = ""
        try:
            body_text = (page.locator("body").inner_text(timeout=5000) or "")[:3000]
        except Exception:
            body_text = ""
        try:
            html_excerpt = (page.content() or "")[:6000]
        except Exception:
            html_excerpt = ""
        lowered_body = body_text.lower()
        lowered_title = title.lower()
        lowered_url = url.lower()
        lowered_html = html_excerpt.lower()
        has_challenge = any(
            marker in lowered_body or marker in lowered_title or marker in lowered_url or marker in lowered_html
            for marker in [
                "just a moment",
                "checking your browser",
                "verify you are human",
                "security verification",
                "performing security verification",
                "cf-browser-verification",
                "cloudflare",
                "turnstile",
                "private access token challenge",
                "challenges.cloudflare.com",
            ]
        )
        has_prompt_input = self._find_prompt_input() is not None
        has_login_prompt = any(
            marker in lowered_body
            for marker in [
                "sign in",
                "log in",
                "continue with x",
            ]
        )
        if has_prompt_input:
            has_login_prompt = False
        return {
            "title": title,
            "url": url,
            "body_text": body_text,
            "has_challenge": has_challenge,
            "has_login_prompt": has_login_prompt,
        }

    def _upload_source_image_if_present(self) -> None:
        page = self._require_page()
        source_image = self.context.request_payload.get("source_image") if self.context.request_payload else None
        if not isinstance(source_image, dict):
            return

        file_path = str(source_image.get("file_path") or "").strip()
        mime_type = str(source_image.get("mime_type") or "").strip().lower()
        if not file_path:
            return
        source_path = Path(file_path)
        if not source_path.exists() or not source_path.is_file():
            raise ProviderAutomationError(
                "SOURCE_IMAGE_NOT_FOUND",
                f"Configured source image does not exist: {file_path}",
            )
        if mime_type and not mime_type.startswith("image/"):
            raise ProviderAutomationError(
                "SOURCE_IMAGE_INVALID",
                f"Configured source file is not an image: {mime_type}",
            )

        try:
            prompt_input = self._find_prompt_input()
            if prompt_input is not None:
                prompt_input.click(timeout=2000)
                page.wait_for_timeout(500)
        except Exception:
            pass

        # Prefer the existing hidden file input. Clicking Grok's upload button
        # can open a native file chooser in a CDP browser and leave automation
        # waiting there, so only click the picker if no input exists yet.
        file_input_selectors = [
            'input[type="file"]',
            'input[type="file"][name="files"]',
            'input[type="file"][accept*="image"]',
            'input[type="file"][multiple]',
        ]

        upload_input = None
        for selector in file_input_selectors:
            try:
                candidate = page.locator(selector).first
                if candidate.count() > 0:
                    upload_input = candidate
                    break
            except Exception:
                continue

        # If no file input found, try clicking the "+" button to reveal upload area
        if upload_input is None:
            self._open_upload_picker()

            # Re-try finding the file input after clicking
            for selector in file_input_selectors:
                try:
                    candidate = page.locator(selector).first
                    if candidate.count() > 0:
                        upload_input = candidate
                        break
                except Exception:
                    continue

        if upload_input is None:
            raise ProviderAutomationError(
                "SOURCE_IMAGE_UPLOAD_FAILED",
                "Could not locate file upload input on Grok Imagine",
                artifacts=self._collect_debug_artifacts("grok-source-image-no-input"),
            )

        try:
            upload_input.set_input_files(str(source_path), timeout=30000)
            preview_ready = self._wait_for_uploaded_image_preview(str(source_path))
            self._append_job_debug_log(
                f"generate: source_image_uploaded preview_ready={preview_ready} path={source_path.name}"
            )
        except Exception as exc:
            raise ProviderAutomationError(
                "SOURCE_IMAGE_UPLOAD_FAILED",
                f"Failed to upload source image into Grok: {exc}",
                artifacts=self._collect_debug_artifacts("grok-source-image-upload-failed"),
            ) from exc

    def _open_upload_picker(self) -> bool:
        page = self._require_page()
        selectors = [
            'button[aria-label*="upload" i]',
            'button[aria-label*="attach" i]',
            'button[aria-label*="add" i]',
            '[role="button"][aria-label*="upload" i]',
            '[role="button"][aria-label*="attach" i]',
            '[role="button"][aria-label*="add" i]',
            'button:has-text("+")',
        ]
        for selector in selectors:
            try:
                locator = page.locator(selector)
                count = locator.count()
            except Exception:
                continue
            for index in range(count):
                button = locator.nth(index)
                try:
                    if button.is_visible(timeout=1000):
                        button.click(timeout=2000)
                        page.wait_for_timeout(1000)
                        return True
                except Exception:
                    continue

        try:
            clicked = page.evaluate(
                """
                () => {
                  const prompt = document.querySelector('[contenteditable="true"], textarea');
                  const root = prompt ? prompt.closest('form, [role="form"], main, div') : document;
                  const nodes = Array.from((root || document).querySelectorAll('button, [role="button"]'));
                  for (const node of nodes) {
                    const label = String(node.getAttribute('aria-label') || node.textContent || '').toLowerCase();
                    const disabled = node.hasAttribute('disabled') || node.getAttribute('aria-disabled') === 'true';
                    if (disabled) continue;
                    if (label.includes('upload') || label.includes('attach') || label.includes('add') || label.trim() === '+') {
                      node.click();
                      return true;
                    }
                  }
                  return false;
                }
                """
            )
            if clicked:
                page.wait_for_timeout(1000)
                return True
        except Exception:
            pass
        return False

    def _wait_for_uploaded_image_preview(self, file_path: str, timeout_ms: int = 30000) -> bool:
        page = self._require_page()
        file_name = Path(file_path).name.lower()
        deadline = time.monotonic() + (timeout_ms / 1000)
        while time.monotonic() < deadline:
            try:
                has_preview = page.evaluate(
                    """
                    fileName => {
                      const images = Array.from(document.querySelectorAll('img'));
                      if (images.some(img => {
                        const alt = String(img.getAttribute('alt') || '').toLowerCase();
                        const src = String(img.getAttribute('src') || '').toLowerCase();
                        return alt.includes(fileName) || src.startsWith('blob:') || src.startsWith('data:image/');
                      })) return true;
                      return Array.from(document.querySelectorAll('[aria-label], [data-testid]')).some(node => {
                        const label = String(node.getAttribute('aria-label') || node.getAttribute('data-testid') || '').toLowerCase();
                        return label.includes('image') && (label.includes('remove') || label.includes('preview') || label.includes('uploaded'));
                      });
                    }
                    """,
                    file_name,
                )
                if has_preview:
                    return True
            except Exception:
                pass
            page.wait_for_timeout(1000)
        return False

    def _select_video_options(self) -> None:
        """Select video resolution and duration from request_payload on Grok Imagine.

        Supported options (read from request_payload):
          - video_resolution: "480p" | "720p"  (default: 480p)
          - video_duration: "6s" | "10s"       (default: 6s)
        """
        request_payload = self.context.request_payload or {}

        video_resolution = str(request_payload.get("video_resolution") or "480p").strip().lower()
        video_duration = str(request_payload.get("video_duration") or "6s").strip().lower()

        if video_resolution in ("480p", "720p"):
            self._select_video_option(video_resolution, ["resolution", "quality", "480p", "720p"])

        if video_duration in ("6s", "10s"):
            self._select_video_option(video_duration, ["duration", "seconds", "6s", "10s"])

    def _select_video_option(self, value: str, trigger_markers: list[str]) -> bool:
        page = self._require_page()
        if self._click_visible_text_option(value):
            return True

        lowered_markers = [marker.lower() for marker in trigger_markers]
        try:
            triggers = page.locator("button, [role='button']")
            count = triggers.count()
        except Exception:
            count = 0
        for index in range(count):
            trigger = triggers.nth(index)
            try:
                text = (trigger.inner_text(timeout=500) or "").strip().lower()
                label = (trigger.get_attribute("aria-label") or "").strip().lower()
                if not any(marker in text or marker in label for marker in lowered_markers):
                    continue
                if not trigger.is_visible(timeout=1000):
                    continue
                trigger.click(timeout=2000)
                page.wait_for_timeout(500)
                if self._click_visible_text_option(value):
                    return True
            except Exception:
                continue
        return False

    def _click_visible_text_option(self, value: str) -> bool:
        page = self._require_page()
        selectors = [
            f'button:has-text("{value}")',
            f'[role="button"]:has-text("{value}")',
            f'[role="option"]:has-text("{value}")',
            f'[cmdk-item]:has-text("{value}")',
        ]
        for selector in selectors:
            try:
                locator = page.locator(selector)
                count = locator.count()
            except Exception:
                continue
            for index in range(count):
                option = locator.nth(index)
                try:
                    if option.is_visible(timeout=1000):
                        option.click(timeout=2000)
                        page.wait_for_timeout(500)
                        return True
                except Exception:
                    continue
        return False

    def _dismiss_overlays(self) -> None:
        """Dismiss any modal dialog, cookie consent, or overlay that blocks interaction."""
        page = self._require_page()
        # Try common dismiss patterns
        dismiss_selectors = [
            # Cookie consent buttons
            'button:has-text("Accept")',
            'button:has-text("Allow all")',
            'button:has-text("Cho phép tất cả")',
            'button:has-text("Reject all")',
            'button:has-text("Từ chối tất cả")',
            'button:has-text("Got it")',
            'button:has-text("OK")',
            # Dialog close buttons
            '[data-state="open"] button[aria-label="Close"]',
            '[data-state="open"] button:has-text("Close")',
            'div[role="dialog"] button[aria-label="Close"]',
            'div[role="dialog"] button:has-text("Close")',
            # Generic close/dismiss
            '#dialog-portal button',
            'button[aria-label="Dismiss"]',
        ]
        for selector in dismiss_selectors:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=1000):
                    btn.click()
                    page.wait_for_timeout(1000)
                    # Check if overlay is gone
                    overlay = page.locator('[data-state="open"][aria-hidden="true"]')
                    if overlay.count() == 0:
                        return
            except Exception:
                continue

        # If overlays still present, try pressing Escape
        try:
            overlay = page.locator('[data-state="open"][aria-hidden="true"]')
            if overlay.count() > 0:
                page.keyboard.press("Escape")
                page.wait_for_timeout(1000)
        except Exception:
            pass

        # Last resort: try to force-remove the overlay via JavaScript
        try:
            page.evaluate("""
                () => {
                    const portal = document.querySelector('#dialog-portal');
                    if (portal) portal.remove();
                    const overlays = document.querySelectorAll('[data-state="open"][aria-hidden="true"]');
                    overlays.forEach(el => el.remove());
                }
            """)
            page.wait_for_timeout(500)
        except Exception:
            pass

    def _find_prompt_input(self):
        page = self._require_page()
        selector_candidates = [
            '[contenteditable="true"]',
            'textarea',
            '[data-testid="composer-text-input"]',
            'textarea[placeholder*="Ask"]',
            'textarea[placeholder*="message"]',
        ]
        for selector in selector_candidates:
            try:
                locator = page.locator(selector)
                count = locator.count()
            except Exception:
                continue
            for index in range(count):
                candidate = locator.nth(index)
                try:
                    if candidate.is_visible(timeout=1500):
                        return candidate
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
        artifacts: list[ProviderArtifact] = []
        try:
            screenshot = page.screenshot(full_page=True)
            artifacts.append(
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
                )
            )
        except Exception:
            pass
        try:
            html_snapshot = page.content()
            artifacts.append(
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
                )
            )
        except Exception:
            pass
        return artifacts

    def _collect_generated_image_artifacts(self) -> list[ProviderArtifact]:
        page = self._require_page()
        self._append_job_debug_log("image_collect: start")
        self._wait_for_image_candidates_to_stabilize()
        collected_artifacts: list[ProviderArtifact] = []
        seen_sources: set[str] = set()
        dom_candidates = self._find_generated_image_candidates()
        for candidate_data in dom_candidates:
            src = str(candidate_data.get("src") or "")
            selector = str(candidate_data.get("selector") or "dom_candidate")
            width = int(candidate_data.get("width") or 0)
            height = int(candidate_data.get("height") or 0)
            score = int(candidate_data.get("score") or 0)
            source_key = self._image_source_key(src)
            if source_key in seen_sources:
                continue
            self._append_job_debug_log(
                f"image_collect: dom_candidate selector={selector} size={width}x{height} score={score} src={src[:180]}"
            )
            if src.startswith("data:image/"):
                parsed_data_url = self._parse_image_data_url(src)
                if parsed_data_url is not None:
                    payload, mime_type = parsed_data_url
                    self._append_job_debug_log(
                        f"image_collect: data_url_ok selector={selector} bytes={len(payload)} mime={mime_type}"
                    )
                    artifact = self._build_image_artifact(
                        payload=payload,
                        mime_type=mime_type,
                        selector=selector,
                        src="data:image",
                        width=width,
                        height=height,
                        score=score,
                        index=len(collected_artifacts),
                        collection_strategy="dom_candidate_data_url",
                    )
                    collected_artifacts.append(artifact)
                    seen_sources.add(source_key)
                    if len(collected_artifacts) >= 8:
                        break
                    continue
            if src.startswith(("http://", "https://")):
                downloaded = self._download_resource_from_page(src, timeout_ms=120000)
                if downloaded is None:
                    downloaded = self._download_authenticated_resource(src)
                if downloaded is not None:
                    payload, mime_type = downloaded
                    if self._looks_like_tracking_image(payload, mime_type):
                        self._append_job_debug_log(
                            f"image_collect: skip_tracking_payload selector={selector} bytes={len(payload)} mime={mime_type}"
                        )
                        continue
                    if len(payload) < 4096 and max(width, height) < 256:
                        self._append_job_debug_log(
                            f"image_collect: skip_tiny_payload selector={selector} bytes={len(payload)} size={width}x{height}"
                        )
                        continue
                    self._append_job_debug_log(
                        f"image_collect: download_ok selector={selector} bytes={len(payload)} mime={mime_type}"
                    )
                    artifact = self._build_image_artifact(
                        payload=payload,
                        mime_type=mime_type,
                        selector=selector,
                        src=src,
                        width=width,
                        height=height,
                        score=score,
                        index=len(collected_artifacts),
                        collection_strategy="dom_candidate_request",
                    )
                    collected_artifacts.append(artifact)
                    seen_sources.add(source_key)
                    if len(collected_artifacts) >= 8:
                        break

        if collected_artifacts:
            self._append_job_debug_log(f"image_collect: multi_artifact_count={len(collected_artifacts)}")
            return collected_artifacts

        image_selectors = [
            'article img[src^="https://"]',
            'main article img[src^="https://"]',
            'img[src^="blob:"]',
            'img[src^="https://"]',
            'img[alt*="Generated"]',
            'main img',
        ]
        for selector in image_selectors:
            locator = page.locator(selector)
            try:
                count = locator.count()
            except Exception:
                continue
            for index in range(count - 1, -1, -1):
                candidate = locator.nth(index)
                try:
                    src = candidate.evaluate("node => node.currentSrc || node.src || ''")
                    normalized_src = str(src or "").lower()
                    if normalized_src and not self._looks_like_generated_image_url(normalized_src):
                        self._append_job_debug_log(
                            f"image_collect: skip_non_generated selector={selector} src={str(src)[:180]}"
                        )
                        continue
                    if src and src.startswith(("http://", "https://")):
                        self._append_job_debug_log(f"image_collect: found_src selector={selector} src={src[:240]}")
                        downloaded = self._download_resource_from_page(src, timeout_ms=120000)
                        if downloaded is None:
                            downloaded = self._download_authenticated_resource(src)
                        if downloaded is not None:
                            payload, mime_type = downloaded
                            if self._looks_like_tracking_image(payload, mime_type):
                                self._append_job_debug_log(
                                    f"image_collect: skip_tracking_payload selector={selector} bytes={len(payload)} mime={mime_type}"
                                )
                                continue
                            extension = ".png"
                            if mime_type == "image/jpeg":
                                extension = ".jpg"
                            elif mime_type == "image/webp":
                                extension = ".webp"
                            elif mime_type == "image/gif":
                                extension = ".gif"
                            self._append_job_debug_log(
                                f"image_collect: download_ok selector={selector} bytes={len(payload)} mime={mime_type}"
                            )
                            return [
                                self._build_image_artifact(
                                    payload=payload,
                                    mime_type=mime_type,
                                    selector=selector,
                                    src=src,
                                    width=0,
                                    height=0,
                                    score=0,
                                    index=0,
                                    collection_strategy="browser_context_request",
                                )
                            ]
                    try:
                        if not candidate.is_visible(timeout=1500):
                            continue
                    except Exception:
                        continue
                    return [
                        ProviderArtifact(
                            artifact_type="image",
                            file_name="grok-generated.png",
                            mime_type="image/png",
                            binary_content=candidate.screenshot(),
                            metadata={
                                "provider": self.provider_name,
                                "selector": selector,
                                "src": src,
                                "collection_strategy": "image_screenshot_fallback",
                            },
                        )
                    ]
                except Exception:
                    continue

        try:
            fallback_src = page.evaluate(
                """
                () => {
                    const html = document.documentElement.innerHTML;
                    const match1 = html.match(/https:\\/\\/assets\\.grok\\.com\\/users\\/[^"'\\s]+\\.(?:jpg|png|jpeg|webp)(?:\\?[^"'\\s]+)?/i);
                    if (match1 && match1[0]) return match1[0];
                    return null;
                }
                """
            )
            if fallback_src:
                self._append_job_debug_log(f"image_collect: fallback_src src={fallback_src[:240]}")
                downloaded = self._download_resource_from_page(fallback_src, timeout_ms=120000)
                if downloaded is None:
                    downloaded = self._download_authenticated_resource(fallback_src)
                    if downloaded is not None:
                        payload, mime_type = downloaded
                        extension = ".png"
                        if mime_type == "image/jpeg":
                            extension = ".jpg"
                        elif mime_type == "image/webp":
                            extension = ".webp"
                        return [
                        self._build_image_artifact(
                            payload=payload,
                            mime_type=mime_type,
                            selector="json_state_fallback",
                            src=fallback_src,
                            width=0,
                            height=0,
                            score=0,
                            index=0,
                            collection_strategy="browser_context_request",
                        )
                    ]
        except Exception as exc:
            self._append_job_debug_log(f"image_collect: fallback_eval_failed error={exc}")
            pass

        self._append_job_debug_log("image_collect: no_artifact_found")
        return []

    def _wait_for_image_candidates_to_stabilize(self, timeout_ms: int = 90000) -> None:
        page = self._require_page()
        deadline = time.monotonic() + (timeout_ms / 1000)
        best_count = 0
        stable_rounds = 0
        last_signature = ""
        while time.monotonic() < deadline:
            candidates = self._find_generated_image_candidates()
            signature = "|".join(
                self._image_source_key(str(item.get("src") or ""))
                for item in candidates[:12]
                if isinstance(item, dict)
            )
            count = len(candidates)
            if count != best_count or signature != last_signature:
                self._append_job_debug_log(
                    f"image_collect: wait_candidates count={count} best={best_count} stable={stable_rounds}"
                )
                best_count = max(best_count, count)
                stable_rounds = 0
                last_signature = signature
            else:
                stable_rounds += 1

            if count >= 8 and stable_rounds >= 1:
                break
            if count >= 4 and stable_rounds >= 3:
                break
            if count > 0 and stable_rounds >= 6:
                break
            page.wait_for_timeout(2000)
        self._append_job_debug_log(
            f"image_collect: wait_done best={best_count} stable={stable_rounds}"
        )

    def _find_generated_image_candidates(self) -> list[dict[str, object]]:
        page = self._require_page()
        try:
            candidates = page.evaluate(
                """
                () => {
                  const nodes = Array.from(document.querySelectorAll('img'));
                  const rows = [];
                  for (const node of nodes) {
                    const rect = node.getBoundingClientRect();
                    const width = Math.round(rect.width || node.clientWidth || node.naturalWidth || 0);
                    const height = Math.round(rect.height || node.clientHeight || node.naturalHeight || 0);
                    const visible = !!(rect.width || rect.height || node.getClientRects().length);
                    if (!visible) continue;
                    const src = node.currentSrc || node.src || '';
                    if (!src) continue;
                    const alt = (node.getAttribute('alt') || '').toLowerCase();
                    const className = String(node.className || '').toLowerCase();
                    const parentButton = node.closest('button,[role="button"],a');
                    const parentLabel = (
                      parentButton?.getAttribute('aria-label')
                      || parentButton?.getAttribute('title')
                      || parentButton?.textContent
                      || ''
                    ).toLowerCase();
                    const inForm = !!node.closest('form,.query-bar,[contenteditable="true"],textarea');
                    const inMain = !!node.closest('main');
                    const inArticle = !!node.closest('article');
                    const favoriteLike = alt.includes('favorite') || parentLabel.includes('saved') || parentLabel.includes('favorite');
                    const roundedLike = className.includes('rounded-full');
                    const smallLike = width < 160 || height < 160;
                    const hugeEnough = width >= 220 && height >= 220;
                    if (inForm || favoriteLike || roundedLike || smallLike || !hugeEnough) continue;
                    let score = width * height;
                    if (inMain) score += 250000;
                    if (inArticle) score += 150000;
                    if (src.startsWith('blob:')) score -= 10000;
                    rows.push({
                      selector: inArticle ? 'article img' : (inMain ? 'main img' : 'img'),
                      src,
                      width,
                      height,
                      alt,
                      score,
                    });
                  }
                  rows.sort((a, b) => (b.score - a.score) || (b.height - a.height) || (b.width - a.width));
                  return rows.slice(0, 12);
                }
                """
            )
        except Exception as exc:
            self._append_job_debug_log(f"image_collect: dom_candidate_eval_failed error={exc}")
            return []
        if not isinstance(candidates, list):
            return []
        return [item for item in candidates if isinstance(item, dict)]

    def _parse_image_data_url(self, value: str) -> tuple[bytes, str] | None:
        if not value.startswith("data:image/"):
            return None
        try:
            header, encoded = value.split(",", 1)
        except ValueError:
            return None
        mime_type = "image/png"
        if ";" in header:
            mime_type = header[5:header.index(";")] or mime_type
        if not header.endswith(";base64"):
            return None
        try:
            return base64.b64decode(encoded), mime_type
        except Exception:
            return None

    def _build_image_artifact(
        self,
        payload: bytes,
        mime_type: str,
        selector: str,
        src: str,
        width: int,
        height: int,
        score: int,
        index: int,
        collection_strategy: str,
    ) -> ProviderArtifact:
        extension = ".png"
        if mime_type == "image/jpeg":
            extension = ".jpg"
        elif mime_type == "image/webp":
            extension = ".webp"
        elif mime_type == "image/gif":
            extension = ".gif"
        suffix = "" if index == 0 else f"-{index + 1}"
        return ProviderArtifact(
            artifact_type="image",
            file_name=f"grok-generated{suffix}{extension}",
            mime_type=mime_type,
            binary_content=payload,
            metadata={
                "provider": self.provider_name,
                "selector": selector,
                "src": src,
                "width": width,
                "height": height,
                "score": score,
                "collection_strategy": collection_strategy,
            },
        )

    def _image_source_key(self, src: str) -> str:
        value = str(src or "")
        if not value:
            return ""
        if value.startswith("data:image/"):
            return "data:" + hashlib.sha1(value.encode("utf-8")).hexdigest()
        return value

    def _looks_like_generated_image_url(self, src: str) -> bool:
        if not src:
            return False
        lowered = src.lower()
        blocked_markers = [
            "analytics.twitter.com",
            "adsct",
            "pixel",
            "emoji",
            "favicon",
            "avatar",
            "profile_images",
            "abs-0.twimg.com",
            "/icon",
            "/logo",
            "gravatar",
        ]
        if any(marker in lowered for marker in blocked_markers):
            return False
        preferred_markers = [
            "assets.grok.com",
            "imagine-public.x.ai",
            "/generated/",
            "image.jpg",
            "image.png",
            "image.webp",
            "preview_image",
        ]
        return any(marker in lowered for marker in preferred_markers)

    def _looks_like_tracking_image(self, payload: bytes, mime_type: str) -> bool:
        if not payload:
            return True
        lowered_mime = str(mime_type or "").lower()
        if len(payload) <= 64 and ("gif" in lowered_mime or "png" in lowered_mime):
            return True
        return False

    def _collect_generated_video_artifacts(self) -> list[ProviderArtifact]:
        self._append_job_debug_log("video_collect: start")
        video_source = self._wait_for_video_source_across_context(timeout_ms=600000)

        if not video_source:
            self._append_job_debug_log("video_collect: source_not_found_after_context_wait")
            return []

        artifact = self._download_video_source_artifact(video_source, file_name="grok-generated.mp4")
        return [artifact] if artifact is not None else []

    def _collect_current_page_video_artifacts(self) -> list[ProviderArtifact]:
        self._append_job_debug_log("image_collect: optional_video_scan_start")
        video_source = self._read_primary_post_video_source()
        if not video_source:
            self._append_job_debug_log("image_collect: optional_video_not_found")
            return []
        artifact = self._download_video_source_artifact(video_source, file_name="grok-generated-video.mp4")
        if artifact is None:
            self._append_job_debug_log("image_collect: optional_video_download_failed")
            return []
        self._append_job_debug_log("image_collect: optional_video_ready")
        return [artifact]

    def _download_video_source_artifact(self, video_source: dict[str, str], file_name: str) -> ProviderArtifact | None:
        page = self._require_page()
        effective_post_url = self._get_current_post_url() or page.url
        src = video_source["src"]
        self._append_job_debug_log(
            f"video_collect: source_found selector={video_source['selector']} post_url={effective_post_url} src={src[:240]}"
        )
        downloaded = self._download_resource_from_page(src, timeout_ms=120000)
        if downloaded is not None:
            self._append_job_debug_log(f"video_collect: page_fetch_ok bytes={len(downloaded[0])} mime={downloaded[1]}")
        if downloaded is None:
            self._append_job_debug_log("video_collect: page_fetch_failed; trying_context_request")
            downloaded = self._download_authenticated_resource(src, timeout_ms=180000)
            if downloaded is not None:
                self._append_job_debug_log(f"video_collect: context_request_ok bytes={len(downloaded[0])} mime={downloaded[1]}")
        if downloaded is None:
            self._append_job_debug_log("video_collect: all_downloads_failed")
            return []
        payload, mime_type = downloaded
        if not self._looks_like_mp4(payload):
            self._append_job_debug_log(f"video_collect: downloaded_payload_not_mp4 bytes={len(payload)} mime={mime_type}")
            return None
        self._append_job_debug_log(f"video_collect: mp4_ready bytes={len(payload)} mime={mime_type}")
        return ProviderArtifact(
            artifact_type="video",
            file_name=file_name,
            mime_type=mime_type.split(";", 1)[0] or "video/mp4",
            binary_content=payload,
            metadata={
                "provider": self.provider_name,
                "selector": video_source["selector"],
                "src": src,
                "post_url": effective_post_url,
                "collection_strategy": "browser_context_request",
            },
        )

    def _wait_for_video_source_across_context(self, timeout_ms: int = 600000) -> dict[str, str] | None:
        page = self._require_page()
        deadline = time.monotonic() + (timeout_ms / 1000)
        adopted_post_logged = False
        while time.monotonic() < deadline:
            source = self._read_primary_post_video_source()
            if source is not None:
                self._append_job_debug_log(f"video_collect: source_on_current_page url={self._safe_page_url(self._page)}")
                return source

            source = self._adopt_page_with_video_source()
            if source is not None:
                self._append_job_debug_log(f"video_collect: adopted_context_video url={self._safe_page_url(self._page)}")
                return source

            if self._adopt_post_page():
                if not adopted_post_logged:
                    self._append_job_debug_log(f"video_collect: adopted_post_page url={self._safe_page_url(self._page)}")
                    adopted_post_logged = True
                source = self._read_primary_post_video_source()
                if source is not None:
                    self._append_job_debug_log(f"video_collect: source_on_adopted_post_page url={self._safe_page_url(self._page)}")
                    return source

            page.wait_for_timeout(2000)

        source = self._read_primary_post_video_source()
        if source is not None:
            self._append_job_debug_log(f"video_collect: source_found_after_wait url={self._safe_page_url(self._page)}")
            return source
        source = self._adopt_page_with_video_source()
        if source is not None:
            self._append_job_debug_log(f"video_collect: adopted_context_video_after_wait url={self._safe_page_url(self._page)}")
        return source

    def _append_job_debug_log(self, message: str) -> None:
        try:
            logs_dir = Path(self.context.logs_dir)
            logs_dir.mkdir(parents=True, exist_ok=True)
            log_path = logs_dir / "grok-debug.log"
            job_id = str(getattr(self.context, "job_id", "") or "")
            with log_path.open("a", encoding="utf-8") as handle:
                prefix = f" job_id={job_id}" if job_id else ""
                handle.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}{prefix} {message}\n")
        except Exception:
            pass

    def _open_generated_video_page(self) -> bool:
        """Open a new Grok Imagine video result from the current gallery page."""
        page = self._require_page()
        if self._page_has_loaded_video():
            return True

        adopted_post_page = self._adopt_post_page()
        if adopted_post_page:
            self._append_job_debug_log(f"video_collect: adopted_post_page url={self._page.url}")
            if self._page_has_loaded_video() or self._get_current_post_url() is not None:
                return True

        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if self._page_has_loaded_video():
                return True
            adopted_post_page = self._adopt_post_page()
            if adopted_post_page:
                self._append_job_debug_log(f"video_collect: adopted_post_page_during_wait url={self._page.url}")
                if self._page_has_loaded_video() or self._get_current_post_url() is not None:
                    return True
            try:
                candidates = page.locator(
                    'a[href*="/imagine/post/"], '
                    'button[aria-label*="play" i], '
                    '[role="button"][aria-label*="play" i], '
                    '[data-testid*="video" i], '
                    'video, '
                    'video[poster]'
                )
                count = candidates.count()
            except Exception:
                count = 0
            for index in range(count):
                try:
                    item = candidates.nth(index)
                    if not item.is_visible(timeout=1000):
                        continue
                    item.scroll_into_view_if_needed(timeout=1000)
                    item.click(timeout=2000)
                    page.wait_for_timeout(3000)
                    if self._page_has_loaded_video() or self._get_current_post_url() is not None:
                        return True
                except Exception:
                    continue
            try:
                if self._read_primary_post_video_source() is not None:
                    return True
            except Exception:
                pass
            page.wait_for_timeout(3000)
        return self._page_has_loaded_video() or self._get_current_post_url() is not None

    def _wait_for_current_video_source(self, timeout_ms: int = 600000) -> dict[str, str] | None:
        page = self._require_page()
        deadline = time.monotonic() + (timeout_ms / 1000)
        while time.monotonic() < deadline:
            source = self._read_primary_post_video_source()
            if source is not None:
                return source
            source = self._adopt_page_with_video_source()
            if source is not None:
                return source
            if self._adopt_post_page():
                source = self._read_primary_post_video_source()
                if source is not None:
                    return source
            page.wait_for_timeout(2000)
        return self._read_primary_post_video_source() or self._adopt_page_with_video_source()

    def _adopt_page_with_video_source(self) -> dict[str, str] | None:
        browser_context = self._browser_context
        if browser_context is None:
            self._append_job_debug_log("video_collect: adopt_context_video_skipped no_browser_context")
            return None
        current_page = self._page
        for candidate_page in browser_context.pages:
            if candidate_page is current_page:
                continue
            try:
                source = candidate_page.evaluate(
                    """
                    () => {
                      const video = Array.from(document.querySelectorAll('video')).find((node) => {
                        const src = node.currentSrc || node.src || '';
                        return src && !src.startsWith('blob:');
                      });
                      if (video) {
                        return video.currentSrc || video.src || '';
                      }
                      const html = document.documentElement.innerHTML;
                      const match = html.match(/https?:[^"'\\s]+generated_video\\.mp4(?:\\?[^"'\\s]+)?/i);
                      return match ? match[0] : '';
                    }
                    """
                )
            except Exception:
                continue
            if not source:
                continue
            try:
                if "grok.com" not in (candidate_page.url or "") and "assets.grok.com" not in str(source):
                    continue
            except Exception:
                pass
            self._page = candidate_page
            self._append_job_debug_log(
                f"video_collect: adopt_context_video_success url={self._safe_page_url(candidate_page)} src={str(source)[:180]}"
            )
            return {
                "selector": "context_pages_video",
                "src": str(source),
            }
        self._append_job_debug_log("video_collect: adopt_context_video_no_match")
        return None

    def _adopt_post_page(self) -> bool:
        browser_context = self._browser_context
        if browser_context is None:
            self._append_job_debug_log("video_collect: adopt_post_page_skipped no_browser_context")
            return False
        page_urls: list[str] = []
        for candidate_page in browser_context.pages:
            try:
                candidate_url = str(candidate_page.url or "")
            except Exception:
                candidate_url = ""
            if candidate_url:
                page_urls.append(candidate_url)
            if "/imagine/post/" not in candidate_url:
                continue
            if candidate_page is self._page:
                self._append_job_debug_log(
                    f"video_collect: adopt_post_page_already_current url={candidate_url}"
                )
                return True
            self._page = candidate_page
            self._append_job_debug_log(f"video_collect: adopt_post_page_success url={candidate_url}")
            return True
        if page_urls:
            self._append_job_debug_log(
                "video_collect: open_generated_video_page_context_urls="
                + " | ".join(page_urls[:6])
            )
        else:
            self._append_job_debug_log("video_collect: adopt_post_page_no_pages")
        return False

    def _safe_page_url(self, page) -> str:
        try:
            return str(page.url or "")
        except Exception:
            return ""

    def _page_has_loaded_video(self) -> bool:
        return self._read_primary_post_video_source() is not None

    def _find_visible_button_by_label(self, label: str):
        page = self._require_page()
        candidates = [
            page.get_by_role("button", name=label),
            page.locator(f'button[aria-label="{label}"]'),
            page.locator(f'[role="button"][aria-label="{label}"]'),
        ]
        for locator in candidates:
            try:
                count = locator.count()
            except Exception:
                continue
            for index in range(count):
                button = locator.nth(index)
                try:
                    if button.is_visible(timeout=1000):
                        return button
                except Exception:
                    continue
        return None

    def _find_visible_enabled_button_by_label(self, label: str):
        page = self._require_page()
        candidates = [
            page.get_by_role("button", name=label),
            page.locator(f'button[aria-label="{label}"]'),
            page.locator(f'[role="button"][aria-label="{label}"]'),
        ]
        for locator in candidates:
            try:
                count = locator.count()
            except Exception:
                continue
            for index in range(count - 1, -1, -1):
                button = locator.nth(index)
                try:
                    if not button.is_visible(timeout=1000):
                        continue
                    if button.is_disabled():
                        continue
                    return button
                except Exception:
                    continue
        return None

    def _find_button_by_label(self, label: str):
        visible_enabled = self._find_visible_enabled_button_by_label(label)
        if visible_enabled is not None:
            return visible_enabled

        page = self._require_page()
        candidates = [
            page.get_by_role("button", name=label),
            page.locator(f'button[aria-label="{label}"]'),
            page.locator(f'[role="button"][aria-label="{label}"]'),
        ]
        for locator in candidates:
            try:
                count = locator.count()
            except Exception:
                continue
            for index in range(count - 1, -1, -1):
                button = locator.nth(index)
                try:
                    if button.is_disabled():
                        continue
                except Exception:
                    continue
                return button
        return None

    def _click_button_with_fallback(self, button) -> bool:
        try:
            button.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass
        try:
            button.click(timeout=2000)
            return True
        except Exception:
            pass
        try:
            button.click(timeout=2000, force=True)
            return True
        except Exception:
            pass
        try:
            button.evaluate("(node) => node.click()")
            return True
        except Exception:
            return False

    def _trigger_button_by_label(self, label: str) -> bool:
        button = self._find_button_by_label(label)
        if button is not None and self._click_button_with_fallback(button):
            return True

        page = self._require_page()
        try:
            clicked_count = page.evaluate(
                """
                label => {
                  const loweredLabel = String(label || '').trim().toLowerCase();
                  if (!loweredLabel) return 0;
                  const nodes = Array.from(document.querySelectorAll('button, [role="button"]'));
                  let clicked = 0;
                  for (const node of nodes) {
                    const ariaLabel = String(node.getAttribute('aria-label') || '').trim().toLowerCase();
                    const text = String(node.textContent || '').trim().toLowerCase();
                    const disabled = node.hasAttribute('disabled') || node.getAttribute('aria-disabled') === 'true';
                    if (disabled) continue;
                    if (ariaLabel === loweredLabel || text === loweredLabel || text.includes(loweredLabel)) {
                      node.click();
                      clicked += 1;
                    }
                  }
                  return clicked;
                }
                """,
                label,
            )
            return bool(clicked_count)
        except Exception:
            return False

    def _wait_for_enabled_button(self, label: str, attempts: int = 24, delay_ms: int = 2500):
        page = self._require_page()
        for _ in range(max(attempts, 1)):
            button = self._find_button_by_label(label)
            if button is not None:
                return button
            page.wait_for_timeout(delay_ms)
        return None

    # _wait_for_video_seed_ready removed — no longer needed.
    # The new Grok Imagine video mode generates video directly from prompt
    # without requiring an intermediate image "seed" step.

    def _read_recent_conversation_links(self, limit: int = 20) -> list[str]:
        page = self._require_page()
        try:
            links = page.evaluate(
                """
                limit => {
                  const hrefs = [];
                  const seen = new Set();
                  for (const node of document.querySelectorAll('a[href]')) {
                    const href = String(node.href || '').trim();
                    if (!href || !href.includes('/c/')) continue;
                    if (seen.has(href)) continue;
                    seen.add(href);
                    hrefs.push(href);
                    if (hrefs.length >= limit) break;
                  }
                  return hrefs;
                }
                """,
                max(limit, 1),
            )
        except Exception:
            return []
        if not isinstance(links, list):
            return []
        return [str(item).strip() for item in links if str(item).strip()]

    def _open_latest_relevant_conversation(self, previous_links: list[str]) -> str | None:
        page = self._require_page()
        previous_set = {item for item in previous_links if item}
        deadline = time.monotonic() + 120
        latest_seen: list[str] = []
        while time.monotonic() < deadline:
            current_post_url = self._get_current_post_url()
            if current_post_url and "/c/" in current_post_url and current_post_url not in previous_set:
                return current_post_url
            latest_seen = self._read_recent_conversation_links()
            for href in latest_seen:
                if href not in previous_set:
                    page.goto(href, wait_until="domcontentloaded")
                    page.wait_for_timeout(3000)
                    return href
            page.wait_for_timeout(2500)

        if latest_seen:
            fallback_href = latest_seen[0]
            if fallback_href not in previous_set:
                page.goto(fallback_href, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
                return fallback_href
        return self._get_current_post_url()

    def _get_current_post_url(self) -> str | None:
        page = self._require_page()
        try:
            canonical = page.locator('link[rel="canonical"]').get_attribute("href")
        except Exception:
            canonical = None
        for candidate in [canonical, page.url]:
            if not candidate:
                continue
            if "/imagine/post/" in candidate:
                return candidate
            if "/imagine" in candidate:
                return candidate
            if "grok.com/c/" in candidate or candidate.startswith("/c/"):
                return candidate
        return None

    def _read_primary_post_video_source(self) -> dict[str, str] | None:
        page = self._require_page()
        try:
            sources = page.evaluate(
                """
                () => {
                  const selectors = [
                    'article video#sd-video',
                    'article video[src]',
                    'main article video[src]',
                    'main video[src]',
                    'video[src]',
                    'video',
                  ];
                      const results = [];
                      for (const selector of selectors) {
                        for (const node of document.querySelectorAll(selector)) {
                          const src = node.currentSrc || node.src || '';
                          if (!src) continue;
                          // Skip blob: URLs - we can't download them directly
                          if (src.startsWith('blob:')) continue;
                          if (src.includes('/share-videos/')) continue;
                          results.push({ selector, src, visible: !!(node.offsetWidth || node.offsetHeight || node.getClientRects().length) });
                        }
                      }
                  // Also check <video> elements with <source> children
                  if (results.length === 0) {
                    for (const video of document.querySelectorAll('video')) {
                      const sourceEl = video.querySelector('source[src]');
                      if (sourceEl) {
                        const src = sourceEl.src || sourceEl.getAttribute('src') || '';
                        if (src && !src.startsWith('blob:') && !src.includes('/share-videos/')) {
                          results.push({ selector: 'video > source', src, visible: true });
                        }
                      }
                    }
                  }
                  // Fallback: scan HTML for user-generated video URLs
                  if (results.length === 0) {
                      const html = document.documentElement.innerHTML;
                      // Match assets.grok.com/users/... .mp4
                      const match1 = html.match(/https:\\/\\/assets\\.grok\\.com\\/users\\/[^"'\\s]+\\.mp4(?:\\?[^"'\\s]+)?/i);
                      if (match1 && match1[0]) {
                          results.push({ selector: "regex_html", src: match1[0], visible: true });
                      }
                      // Match imagine-public.x.ai but exclude known template videos
                      if (results.length === 0) {
                          const allMp4 = html.matchAll(/https:\\/\\/imagine-public\\.x\\.ai\\/[^"'\\s]+\\.mp4(?:\\?[^"'\\s]+)?/gi);
                          const knownTemplates = new Set([
                              'https://imagine-public.x.ai/imagine-public/share-videos/7b097052-8cfe-4b0f-8a33-c2a71e1aed25.mp4'
                          ]);
                          for (const m of allMp4) {
                              if (!knownTemplates.has(m[0])) {
                                  results.push({ selector: "regex_html_imagine", src: m[0], visible: true });
                                  break;
                              }
                          }
                      }
                  }
                  // Fallback: scan Performance API for video resources
                  if (results.length === 0) {
                      try {
                          const entries = performance.getEntriesByType('resource');
                          for (const entry of entries) {
                              const name = entry.name || '';
                              if (
                                  (name.includes('.mp4') || name.includes('video/')) &&
                                  !name.includes('share-videos/') &&
                                  (name.includes('assets.grok.com') || name.includes('imagine-public.x.ai') || name.includes('grok.com'))
                              ) {
                                  results.push({ selector: 'performance_api', src: name, visible: true });
                              }
                          }
                      } catch(e) {}
                  }
                  return results;
                }
                """
            )
        except Exception as exc:
            self._append_job_debug_log(f"video_collect: read_source_eval_failed error={exc}")
            return None
        if not isinstance(sources, list):
            return None
        for item in sources:
            if isinstance(item, dict) and item.get("src"):
                return {
                    "selector": str(item.get("selector") or "article video"),
                    "src": str(item.get("src")),
                }
        # Fallback: check captured video URLs from network interception
        if self._captured_video_urls:
            preferred_urls = []
            for url in self._captured_video_urls:
                if "share-videos/" in url:
                    continue
                if (
                    "assets.grok.com" in url
                    or "generated_video" in url
                    or "/generated/" in url
                ):
                    preferred_urls.append(url)
            for url in preferred_urls:
                if "assets.grok.com" in url or "generated_video" in url or "/generated/" in url:
                    return {
                        "selector": "network_intercept",
                        "src": url,
                    }
        return None

    def _download_authenticated_resource(self, url: str, timeout_ms: int = 120000) -> tuple[bytes, str] | None:
        browser_context = self._require_browser_context()
        try:
            response = browser_context.request.get(
                url,
                headers={"Referer": "https://grok.com/", "Accept": "*/*"},
                timeout=timeout_ms
            )
        except Exception:
            return None
        if not response.ok:
            return None
        try:
            payload = response.body()
        except Exception:
            return None
        mime_type = (
            response.headers.get("content-type")
            or mimetypes.guess_type(url)[0]
            or "application/octet-stream"
        )
        return payload, mime_type.split(";", 1)[0]

    def _download_resource_from_page(self, url: str, timeout_ms: int = 120000) -> tuple[bytes, str] | None:
        page = self._require_page()
        try:
            result = page.evaluate(
                """
                async ({ url, timeoutMs }) => {
                  const controller = new AbortController();
                  const timer = setTimeout(() => controller.abort(), timeoutMs);
                  try {
                    const response = await fetch(url, {
                      credentials: 'include',
                      cache: 'no-store',
                      signal: controller.signal,
                    });
                    if (!response.ok) {
                      return { ok: false, status: response.status, contentType: response.headers.get('content-type') || '' };
                    }
                    const contentType = response.headers.get('content-type') || '';
                    const buffer = await response.arrayBuffer();
                    const bytes = new Uint8Array(buffer);
                    let binary = '';
                    const chunkSize = 0x8000;
                    for (let i = 0; i < bytes.length; i += chunkSize) {
                      binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
                    }
                    return { ok: true, contentType, bodyBase64: btoa(binary) };
                  } finally {
                    clearTimeout(timer);
                  }
                }
                """,
                {"url": url, "timeoutMs": timeout_ms},
            )
        except Exception:
            return None
        if not isinstance(result, dict) or not result.get("ok"):
            return None
        body_base64 = str(result.get("bodyBase64") or "")
        if not body_base64:
            return None
        try:
            payload = base64.b64decode(body_base64)
        except Exception:
            return None
        mime_type = str(result.get("contentType") or mimetypes.guess_type(url)[0] or "application/octet-stream")
        return payload, mime_type.split(";", 1)[0]

    @staticmethod
    def _looks_like_mp4(payload: bytes) -> bool:
        if len(payload) < 12:
            return False
        if payload.startswith(b"<!DOCTYPE html") or payload.startswith(b"<html"):
            return False
        return b"ftyp" in payload[:64]

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
