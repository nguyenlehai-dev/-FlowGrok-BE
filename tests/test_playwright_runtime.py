from app.services.playwright_runtime import get_browser_cdp_url
from app.worker.providers.base import ProviderExecutionContext


def _build_context(runtime_settings=None) -> ProviderExecutionContext:
    return ProviderExecutionContext(
        job_id="job-1",
        profile_id="profile-1",
        profile_name="Profile",
        provider="grok",
        job_type="generate_image",
        prompt="hello",
        request_payload={},
        headless=True,
        artifacts_dir="/tmp/artifacts",
        logs_dir="/tmp/logs",
        browser_dir="/tmp/browser",
        cache_dir="/tmp/cache",
        storage_state_path=None,
        normalized_cookie_path=None,
        runtime_settings=runtime_settings,
        antidetect_settings=None,
    )


def test_get_browser_cdp_url_prefers_runtime_settings(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_CDP_URL", "http://127.0.0.1:9222")
    context = _build_context({"cdp_url": "http://127.0.0.1:9333"})
    assert get_browser_cdp_url(context) == "http://127.0.0.1:9333"


def test_get_browser_cdp_url_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_CDP_URL", "http://127.0.0.1:9222")
    context = _build_context()
    assert get_browser_cdp_url(context) == "http://127.0.0.1:9222"
