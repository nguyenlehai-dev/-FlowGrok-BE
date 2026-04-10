from app.core.security import get_cors_origins, hash_api_key, verify_api_key, verify_worker_token


def test_hash_api_key_is_deterministic():
    raw_key = "fgk_test_123"
    assert hash_api_key(raw_key) == hash_api_key(raw_key)


def test_verify_api_key_matches_hash():
    raw_key = "fgk_test_456"
    hashed = hash_api_key(raw_key)
    assert verify_api_key(raw_key, hashed) is True
    assert verify_api_key("fgk_other", hashed) is False


def test_verify_worker_token_uses_env(monkeypatch):
    monkeypatch.setenv("WORKER_TOKEN", "worker-secret")
    from importlib import reload
    import app.core.security as security

    reload(security)
    assert security.verify_worker_token("worker-secret") is True
    assert security.verify_worker_token("wrong-secret") is False


def test_get_cors_origins_from_env(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, https://b.example")
    from importlib import reload
    import app.core.security as security

    reload(security)
    assert security.get_cors_origins() == ["https://a.example", "https://b.example"]
