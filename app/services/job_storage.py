from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.profile_storage import BASE_STORAGE_DIR


def ensure_job_directories(job_id: str) -> dict[str, str]:
    job_root = BASE_STORAGE_DIR / "jobs" / job_id
    artifacts_dir = job_root / "artifacts"
    logs_dir = job_root / "logs"

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    return {
        "root": str(job_root),
        "artifacts": str(artifacts_dir),
        "logs": str(logs_dir),
    }


def write_job_log(job_id: str, file_name: str, content: str) -> str:
    directories = ensure_job_directories(job_id)
    target_path = Path(directories["logs"]) / file_name
    target_path.write_text(content, encoding="utf-8")
    return str(target_path)


def write_job_metadata_artifact(job_id: str, file_name: str, payload: dict[str, Any]) -> str:
    directories = ensure_job_directories(job_id)
    target_path = Path(directories["artifacts"]) / file_name
    target_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return str(target_path)


def write_job_text_artifact(job_id: str, file_name: str, content: str) -> str:
    directories = ensure_job_directories(job_id)
    target_path = Path(directories["artifacts"]) / file_name
    target_path.write_text(content, encoding="utf-8")
    return str(target_path)


def write_job_binary_artifact(job_id: str, file_name: str, content: bytes) -> str:
    directories = ensure_job_directories(job_id)
    target_path = Path(directories["artifacts"]) / file_name
    target_path.write_bytes(content)
    return str(target_path)
