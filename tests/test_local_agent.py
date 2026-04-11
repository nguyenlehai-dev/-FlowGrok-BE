from fastapi.testclient import TestClient

from app.local_agent import main as local_agent


def test_local_agent_health():
    client = TestClient(local_agent.app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["service"] == "flowgrok-local-agent"


def test_local_agent_api_key_is_optional_by_default(monkeypatch):
    monkeypatch.setattr(local_agent, "LOCAL_AGENT_API_KEY", "")
    client = TestClient(local_agent.app)

    response = client.get("/api/v1/jobs")

    assert response.status_code == 200


def test_local_agent_api_key_rejects_invalid_key(monkeypatch):
    monkeypatch.setattr(local_agent, "LOCAL_AGENT_API_KEY", "secret")
    client = TestClient(local_agent.app)

    response = client.get("/api/v1/jobs", headers={"X-API-Key": "wrong"})

    assert response.status_code == 401


def test_local_agent_api_key_accepts_bearer(monkeypatch):
    monkeypatch.setattr(local_agent, "LOCAL_AGENT_API_KEY", "secret")
    client = TestClient(local_agent.app)

    response = client.get("/api/v1/jobs", headers={"Authorization": "Bearer secret"})

    assert response.status_code == 200


def test_local_agent_strips_gateway_mode_from_provider_context():
    context = local_agent._build_context(
        job_id="test-local-agent-context",
        profile_id="test-local-agent-profile",
        profile_name="Test Local Agent",
        job_type="generate_image",
        prompt="smoke",
        request_payload={"provider_mode": "gateway", "video_duration": "6s"},
        headless=True,
    )

    assert "provider_mode" not in context.request_payload
    assert context.request_payload["video_duration"] == "6s"
