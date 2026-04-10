from app.worker.providers.base import ProviderAutomationError, ProviderExecutionContext
from app.worker.providers.grok import GrokAutomationProvider


def _build_context() -> ProviderExecutionContext:
    return ProviderExecutionContext(
        job_id="job-1",
        profile_id="profile-1",
        profile_name="Grok Test",
        provider="grok",
        job_type="generate_image",
        prompt="test prompt",
        request_payload={},
        headless=True,
        artifacts_dir="/tmp/artifacts",
        logs_dir="/tmp/logs",
        browser_dir="/tmp/browser",
        cache_dir="/tmp/cache",
        storage_state_path="/tmp/storage_state.json",
        normalized_cookie_path="/tmp/cookies.json",
        runtime_settings=None,
        antidetect_settings=None,
    )


def test_grok_generation_raises_challenge_blocked(monkeypatch):
    provider = GrokAutomationProvider(_build_context())

    monkeypatch.setattr(provider, "_require_page", lambda: object())
    monkeypatch.setattr(
        provider,
        "_goto_grok",
        lambda: {
            "title": "Just a moment...",
            "url": "https://grok.com/i",
            "has_challenge": True,
            "has_login_prompt": False,
            "challenge_wait_ms": 22500,
        },
    )
    monkeypatch.setattr(provider, "_collect_debug_artifacts", lambda slug: [])

    try:
        provider.generate_image()
    except ProviderAutomationError as exc:
        assert exc.code == "CHALLENGE_BLOCKED"
        assert "security challenge" in exc.message
        return

    raise AssertionError("Expected ProviderAutomationError")
