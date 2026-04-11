from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from app.core.logging_utils import configure_logging
from app.core.security import get_cors_origins
from app.db.database import engine, SQLALCHEMY_DATABASE_URL
from app.db.base import Base
from app.db.migrations import run_sqlite_migrations
import app.models.core  # Import để SQLAlchemy nhận diện model và tạo bảng

load_dotenv()
configure_logging()

# Tạo toàn bộ các bảng vào file SQLite khi khởi động
Base.metadata.create_all(bind=engine)
run_sqlite_migrations(engine)

# Import các Routers
from app.api.endpoints import profiles, proxies, auth, jobs

app = FastAPI(title="FlowGrok API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Nhúng các API Endpoints
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(profiles.router, prefix="/api/v1/profiles", tags=["Profiles"])
app.include_router(proxies.router, prefix="/api/v1/proxies", tags=["Proxies"])
app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["Jobs"])
app.include_router(jobs.internal_router, prefix="/api/v1/internal/jobs", tags=["Internal Jobs"])
app.include_router(profiles.external_router, prefix="/api/v1/client/profiles", tags=["Client Profiles"])
app.include_router(jobs.external_router, prefix="/api/v1/client/jobs", tags=["Client Jobs"])

@app.get("/")
def read_root():
    return {"status": "ok", "message": "FlowGrok FastAPI Database Mapped!"}


@app.get("/health")
def read_health():
    return {
        "status": "ok",
        "service": "flowgrok-api",
        "database": {
            "dialect": engine.dialect.name,
            "url": _mask_database_url(SQLALCHEMY_DATABASE_URL),
        },
    }


@app.get("/api/health")
def read_api_health():
    return read_health()


def _mask_database_url(database_url: str) -> str:
    if "://" not in database_url:
        return database_url
    scheme, rest = database_url.split("://", 1)
    if "@" not in rest:
        return database_url
    credentials, host_part = rest.split("@", 1)
    if ":" not in credentials:
        return f"{scheme}://***@{host_part}"
    username, _password = credentials.split(":", 1)
    return f"{scheme}://{username}:***@{host_part}"
