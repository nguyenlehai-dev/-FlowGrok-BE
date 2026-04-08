from __future__ import annotations

from pathlib import Path
from typing import Any

from app.worker.providers.base import ProviderExecutionContext


def get_playwright_sync_api():
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Playwright is not installed in the current Python runtime") from exc
    return sync_playwright


def build_browser_launch_kwargs(context: ProviderExecutionContext) -> dict[str, Any]:
    runtime_settings = context.runtime_settings or {}
    launch_args = runtime_settings.get("launch_args") or []
    if not isinstance(launch_args, list):
        launch_args = []

    return {
        "headless": context.headless,
        "args": [str(item) for item in launch_args],
    }


def build_browser_context_kwargs(context: ProviderExecutionContext) -> dict[str, Any]:
    runtime_settings = context.runtime_settings or {}
    antidetect_settings = context.antidetect_settings or {}
    context_kwargs: dict[str, Any] = {
        "accept_downloads": True,
        "viewport": {
            "width": int(antidetect_settings.get("viewport_width") or 1366),
            "height": int(antidetect_settings.get("viewport_height") or 768),
        },
        "locale": antidetect_settings.get("locale") or "en-US",
        "timezone_id": antidetect_settings.get("timezone") or "UTC",
        "user_agent": antidetect_settings.get("user_agent") or None,
    }

    storage_state_path = context.storage_state_path
    if storage_state_path and Path(storage_state_path).exists():
        context_kwargs["storage_state"] = storage_state_path

    extra_http_headers = runtime_settings.get("extra_http_headers")
    if isinstance(extra_http_headers, dict) and extra_http_headers:
        context_kwargs["extra_http_headers"] = {
            str(key): str(value) for key, value in extra_http_headers.items()
        }

    return {key: value for key, value in context_kwargs.items() if value is not None}
