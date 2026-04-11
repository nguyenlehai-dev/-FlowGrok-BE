from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.worker.providers.base import ProviderExecutionContext


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)

DEFAULT_CHROMIUM_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--disable-features=IsolateOrigins,site-per-process",
    "--disable-infobars",
    "--enable-features=NetworkService,NetworkServiceInProcess",
    "--lang=en-US,en;q=0.9",
    "--no-default-browser-check",
    "--no-first-run",
    "--password-store=basic",
    "--start-maximized",
    "--window-position=40,40",
]


def get_playwright_sync_api():
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Playwright is not installed in the current Python runtime") from exc
    return sync_playwright


def _coerce_int(value: object | None, fallback: int) -> int:
    try:
        return int(value) if value is not None else fallback
    except (TypeError, ValueError):
        return fallback


def _build_accept_language(locale: str) -> str:
    if not locale:
        return "en-US,en;q=0.9"
    language = locale.split("-")[0]
    if language.lower() == locale.lower():
        return f"{locale},{language};q=0.9,en;q=0.8"
    return f"{locale},{language};q=0.9,en;q=0.8"


def _merge_launch_args(runtime_args: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for raw_item in [*DEFAULT_CHROMIUM_ARGS, *runtime_args]:
        item = str(raw_item).strip()
        if not item or item in seen:
            continue
        merged.append(item)
        seen.add(item)
    return merged


def build_browser_launch_kwargs(context: "ProviderExecutionContext") -> dict[str, Any]:
    runtime_settings = context.runtime_settings or {}
    launch_args = runtime_settings.get("launch_args") or []
    if not isinstance(launch_args, list):
        launch_args = []
    headless = context.headless
    if not headless and os.name != "nt" and not os.getenv("DISPLAY"):
        headless = True

    launch_kwargs: dict[str, Any] = {
        "headless": headless,
        "args": _merge_launch_args([str(item) for item in launch_args]),
    }
    channel = runtime_settings.get("channel")
    if channel:
        launch_kwargs["channel"] = str(channel)
    return launch_kwargs


def get_browser_cdp_url(context: "ProviderExecutionContext") -> str | None:
    runtime_settings = context.runtime_settings or {}
    configured = runtime_settings.get("cdp_url")
    if configured:
        return str(configured).strip() or None
    env_value = os.getenv("PLAYWRIGHT_CDP_URL", "").strip()
    return env_value or None


def build_browser_context_kwargs(context: "ProviderExecutionContext") -> dict[str, Any]:
    runtime_settings = context.runtime_settings or {}
    antidetect_settings = context.antidetect_settings or {}
    viewport_width = _coerce_int(antidetect_settings.get("viewport_width"), 1366)
    viewport_height = _coerce_int(antidetect_settings.get("viewport_height"), 768)
    locale = str(antidetect_settings.get("locale") or "en-US")
    timezone_id = str(antidetect_settings.get("timezone") or "UTC")
    user_agent = str(antidetect_settings.get("user_agent") or DEFAULT_USER_AGENT)
    extra_http_headers = runtime_settings.get("extra_http_headers")
    base_headers = {
        "Accept-Language": _build_accept_language(locale),
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
    }
    context_kwargs: dict[str, Any] = {
        "accept_downloads": True,
        "viewport": {
            "width": viewport_width,
            "height": viewport_height,
        },
        "screen": {
            "width": viewport_width,
            "height": viewport_height,
        },
        "locale": locale,
        "timezone_id": timezone_id,
        "user_agent": user_agent,
        "java_script_enabled": True,
        "ignore_https_errors": False,
        "bypass_csp": False,
        "extra_http_headers": base_headers,
    }

    storage_state_path = context.storage_state_path
    if storage_state_path and Path(storage_state_path).exists():
        context_kwargs["storage_state"] = storage_state_path

    if isinstance(extra_http_headers, dict) and extra_http_headers:
        context_kwargs["extra_http_headers"] = {
            **base_headers,
            **{str(key): str(value) for key, value in extra_http_headers.items()},
        }

    return {key: value for key, value in context_kwargs.items() if value is not None}


def build_browser_init_script(context: "ProviderExecutionContext") -> str:
    antidetect_settings = context.antidetect_settings or {}
    locale = str(antidetect_settings.get("locale") or "en-US")
    language = locale.split("-")[0]
    platform = str(antidetect_settings.get("platform") or "Win32")
    hardware_concurrency = _coerce_int(antidetect_settings.get("hardware_concurrency"), 8)
    device_memory = _coerce_int(antidetect_settings.get("device_memory"), 8)
    webgl_vendor = str(antidetect_settings.get("webgl_vendor") or "Google Inc. (Intel)")

    return f"""
(() => {{
  const patchValue = (target, key, value) => {{
    try {{
      Object.defineProperty(target, key, {{
        configurable: true,
        enumerable: true,
        get: () => value,
      }});
    }} catch (_error) {{
      return;
    }}
  }};

  patchValue(Navigator.prototype, 'webdriver', undefined);
  patchValue(Navigator.prototype, 'platform', {platform!r});
  patchValue(Navigator.prototype, 'language', {locale!r});
  patchValue(Navigator.prototype, 'languages', [{locale!r}, {language!r}, 'en']);
  patchValue(Navigator.prototype, 'hardwareConcurrency', {hardware_concurrency});
  patchValue(Navigator.prototype, 'deviceMemory', {device_memory});

  if (!window.chrome) {{
    Object.defineProperty(window, 'chrome', {{
      configurable: true,
      enumerable: true,
      value: {{
        app: {{
          isInstalled: false,
          InstallState: {{ DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' }},
          RunningState: {{ CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }},
        }},
        runtime: {{}},
      }},
    }});
  }}

  if (!Navigator.prototype.plugins || Navigator.prototype.plugins.length === 0) {{
    patchValue(Navigator.prototype, 'plugins', [
      {{ name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' }},
      {{ name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' }},
      {{ name: 'Native Client', filename: 'internal-nacl-plugin', description: '' }},
    ]);
  }}

  if (!Navigator.prototype.mimeTypes || Navigator.prototype.mimeTypes.length === 0) {{
    patchValue(Navigator.prototype, 'mimeTypes', [
      {{ type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' }},
      {{ type: 'text/pdf', suffixes: 'pdf', description: 'Portable Document Format' }},
    ]);
  }}

  const originalQuery = window.navigator.permissions?.query?.bind(window.navigator.permissions);
  if (originalQuery) {{
    window.navigator.permissions.query = (parameters) => (
      parameters?.name === 'notifications'
        ? Promise.resolve({{ state: Notification.permission }})
        : originalQuery(parameters)
    );
  }}

  const originalGetParameter = WebGLRenderingContext.prototype.getParameter;
  WebGLRenderingContext.prototype.getParameter = function(parameter) {{
    if (parameter === 37445) return {webgl_vendor!r};
    if (parameter === 37446) return 'ANGLE (Intel, Intel(R) UHD Graphics Direct3D11 vs_5_0 ps_5_0)';
    return originalGetParameter.call(this, parameter);
  }};

  if ('maxTouchPoints' in Navigator.prototype) {{
    patchValue(Navigator.prototype, 'maxTouchPoints', 0);
  }}
}})();
""".strip()
