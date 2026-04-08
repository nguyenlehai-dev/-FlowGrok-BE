from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.db.database import engine
from app.db.base import Base
from app.db.migrations import run_sqlite_migrations
import app.models.core  # Import để SQLAlchemy nhận diện model và tạo bảng

# Tạo toàn bộ các bảng vào file SQLite khi khởi động
Base.metadata.create_all(bind=engine)
run_sqlite_migrations(engine)

# Import các Routers
from app.api.endpoints import profiles, proxies, auth, jobs

app = FastAPI(title="FlowGrok API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
