from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


DEFAULT_SQLITE_URL = "sqlite:///./flowgrok.db"
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_SQLITE_URL)


def _build_engine():
    engine_kwargs: dict[str, object] = {
        "pool_pre_ping": True,
    }
    if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
        # SQLite cần check_same_thread=False để dùng qua nhiều request/thread.
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(SQLALCHEMY_DATABASE_URL, **engine_kwargs)


engine = _build_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
