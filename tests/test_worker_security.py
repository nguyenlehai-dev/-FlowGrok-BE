from importlib import reload

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


def _build_worker_test_client(monkeypatch, worker_token: str = "worker-secret", limit: int = 240) -> TestClient:
    monkeypatch.setenv("WORKER_TOKEN", worker_token)
    import app.core.security as security
    import app.core.deps as deps

    reload(security)
    reload(deps)

    app = FastAPI()

    @app.post("/protected")
    def protected_route(_token: str = Depends(deps.require_internal_worker)):
        return {"status": "ok"}

    return TestClient(app)


def test_worker_endpoint_requires_token(monkeypatch):
    client = _build_worker_test_client(monkeypatch)
    response = client.post("/protected")
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing worker token"


def test_worker_endpoint_rejects_invalid_token(monkeypatch):
    client = _build_worker_test_client(monkeypatch)
    response = client.post("/protected", headers={"x-worker-token": "wrong-token"})
    assert response.status_code == 403
    assert response.json()["detail"] == "Invalid worker token"


def test_worker_endpoint_rate_limits_after_burst(monkeypatch):
    client = _build_worker_test_client(monkeypatch)
    for _ in range(240):
        response = client.post("/protected", headers={"x-worker-token": "worker-secret"})
        assert response.status_code == 200

    response = client.post("/protected", headers={"x-worker-token": "worker-secret"})
    assert response.status_code == 429
    assert response.json()["detail"] == "Worker rate limit exceeded"
