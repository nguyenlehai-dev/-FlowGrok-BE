from importlib import reload
from pathlib import Path
import sys

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.security import get_password_hash, hash_api_key
from app.db.base import Base
from app.models.core import ApiKey, User


def _build_api_key_test_client(monkeypatch, rate_limit_per_minute: int = 1) -> TestClient:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    user = User(email="rate@example.com", hashed_password=get_password_hash("password"))
    db.add(user)
    db.commit()
    db.refresh(user)

    raw_key = "fgk_rate_limit_test"
    api_key = ApiKey(
        user_id=user.id,
        key="stored_rate_limit_test",
        key_hash=hash_api_key(raw_key),
        key_preview="fgk_rate..._test",
        rate_limit_per_minute=rate_limit_per_minute,
        status="active",
    )
    db.add(api_key)
    db.commit()
    db.close()

    import app.core.security as security
    import app.core.deps as deps
    from app.db.database import get_db

    reload(security)
    reload(deps)

    app = FastAPI()

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    @app.get("/client-protected")
    def client_protected(_client=Depends(deps.get_api_client_context)):
        return {"status": "ok"}

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {raw_key}"})
    return client


def test_api_key_rate_limit_returns_429(monkeypatch):
    client = _build_api_key_test_client(monkeypatch, rate_limit_per_minute=1)
    response = client.get("/client-protected")
    assert response.status_code == 200

    response = client.get("/client-protected")
    assert response.status_code == 429
    assert response.json()["detail"] == "API key rate limit exceeded"


def test_api_key_invalid_returns_401(monkeypatch):
    client = _build_api_key_test_client(monkeypatch, rate_limit_per_minute=5)
    client.headers.update({"Authorization": "Bearer fgk_invalid_key"})
    response = client.get("/client-protected")
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API key"
