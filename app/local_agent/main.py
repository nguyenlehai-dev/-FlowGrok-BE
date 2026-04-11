from __future__ import annotations

import json
import hmac
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.services.job_storage import (
    ensure_job_directories,
    write_job_binary_artifact,
    write_job_metadata_artifact,
    write_job_text_artifact,
)
from app.services.profile_storage import ensure_profile_directories
from app.worker.providers import get_provider_automation
from app.worker.providers.base import ProviderArtifact, ProviderAutomationError, ProviderExecutionContext


LOCAL_AGENT_PROFILE_ID = os.getenv("FLOWGROK_LOCAL_PROFILE_ID", "local-grok")
LOCAL_AGENT_PROFILE_NAME = os.getenv("FLOWGROK_LOCAL_PROFILE_NAME", "Local Grok")
LOCAL_AGENT_API_KEY = os.getenv("FLOWGROK_LOCAL_API_KEY", "").strip()


class LocalJobCreate(BaseModel):
    job_type: Literal["generate_image", "generate_video"]
    prompt: str
    request_payload: dict[str, Any] = Field(default_factory=dict)
    headless: bool = False
    profile_id: str = LOCAL_AGENT_PROFILE_ID
    profile_name: str = LOCAL_AGENT_PROFILE_NAME


class LocalSessionCheck(BaseModel):
    headless: bool = False
    profile_id: str = LOCAL_AGENT_PROFILE_ID
    profile_name: str = LOCAL_AGENT_PROFILE_NAME


@dataclass
class LocalArtifact:
    id: str
    artifact_type: str
    file_path: str
    mime_type: str
    size_bytes: int
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LocalJob:
    id: str
    profile_id: str
    profile_name: str
    provider: str
    job_type: str
    prompt: str
    request_payload: dict[str, Any]
    status: str
    headless: bool
    artifacts: list[LocalArtifact] = field(default_factory=list)
    result_payload: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: str = field(default_factory=lambda: _now_iso())
    started_at: str | None = None
    finished_at: str | None = None


app = FastAPI(
    title="FlowGrok Local Agent",
    version="0.1.0",
    description="Local Grok automation tool with an API surface for user-owned machines.",
)

_jobs: dict[str, LocalJob] = {}
_lock = threading.Lock()


def require_local_api_key(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> None:
    if not LOCAL_AGENT_API_KEY:
        return None
    presented_key = (x_api_key or "").strip()
    if not presented_key and authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer":
            presented_key = value.strip()
    if not presented_key or not hmac.compare_digest(presented_key, LOCAL_AGENT_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid local agent API key")
    return None


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "service": "flowgrok-local-agent",
        "profile_id": LOCAL_AGENT_PROFILE_ID,
        "storage": str(Path("storage").resolve()),
    }


@app.post("/api/v1/session/check")
def check_session(
    payload: LocalSessionCheck,
    _api_key: None = Depends(require_local_api_key),
) -> dict[str, object]:
    job_id = f"session-{uuid4()}"
    context = _build_context(
        job_id=job_id,
        profile_id=payload.profile_id,
        profile_name=payload.profile_name,
        job_type="generate_image",
        prompt="",
        request_payload={},
        headless=payload.headless,
    )
    runtime = None
    try:
        runtime = get_provider_automation(context)
        boot_state = runtime.bootstrap_context()
        login_state = runtime.login_with_cookies()
        return {
            "status": "success",
            "boot_state": boot_state,
            "login_state": login_state,
        }
    except ProviderAutomationError as exc:
        return {
            "status": "error",
            "error_code": exc.code,
            "error_message": exc.message,
        }
    finally:
        if runtime is not None:
            runtime.close()


@app.post("/api/v1/jobs", status_code=202)
def create_job(
    payload: LocalJobCreate,
    background_tasks: BackgroundTasks,
    _api_key: None = Depends(require_local_api_key),
) -> dict[str, object]:
    job = LocalJob(
        id=str(uuid4()),
        profile_id=payload.profile_id,
        profile_name=payload.profile_name,
        provider="grok",
        job_type=payload.job_type,
        prompt=payload.prompt,
        request_payload=payload.request_payload,
        status="queued",
        headless=payload.headless,
    )
    with _lock:
        _jobs[job.id] = job
    background_tasks.add_task(_run_job, job.id)
    return _job_response(job)


@app.get("/api/v1/jobs")
def list_jobs(_api_key: None = Depends(require_local_api_key)) -> list[dict[str, object]]:
    with _lock:
        jobs = sorted(_jobs.values(), key=lambda item: item.created_at, reverse=True)
        return [_job_response(job) for job in jobs]


@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str, _api_key: None = Depends(require_local_api_key)) -> dict[str, object]:
    return _job_response(_get_job(job_id))


@app.get("/api/v1/jobs/{job_id}/artifacts")
def list_artifacts(job_id: str, _api_key: None = Depends(require_local_api_key)) -> list[dict[str, object]]:
    job = _get_job(job_id)
    return [asdict(artifact) for artifact in job.artifacts]


@app.get("/api/v1/jobs/{job_id}/artifacts/{artifact_id}/content")
def get_artifact_content(
    job_id: str,
    artifact_id: str,
    _api_key: None = Depends(require_local_api_key),
):
    job = _get_job(job_id)
    for artifact in job.artifacts:
        if artifact.id == artifact_id:
            path = Path(artifact.file_path)
            if not path.exists() or not path.is_file():
                raise HTTPException(status_code=404, detail="Artifact file not found")
            return FileResponse(
                path=str(path),
                media_type=artifact.mime_type,
                filename=path.name,
                content_disposition_type="inline",
            )
    raise HTTPException(status_code=404, detail="Artifact not found")


def _run_job(job_id: str) -> None:
    with _lock:
        job = _jobs[job_id]
        job.status = "running"
        job.started_at = _now_iso()

    context = _build_context(
        job_id=job.id,
        profile_id=job.profile_id,
        profile_name=job.profile_name,
        job_type=job.job_type,
        prompt=job.prompt,
        request_payload=job.request_payload,
        headless=job.headless,
    )
    runtime = None
    try:
        runtime = get_provider_automation(context)
        boot_state = runtime.bootstrap_context()
        login_state = runtime.login_with_cookies()
        provider_artifacts = (
            runtime.generate_video()
            if job.job_type == "generate_video"
            else runtime.generate_image()
        )
        local_artifacts = _persist_artifacts(job.id, provider_artifacts)
        metadata_path = write_job_metadata_artifact(
            job.id,
            "local-agent-result.json",
            {
                "job_id": job.id,
                "profile_id": job.profile_id,
                "provider": job.provider,
                "job_type": job.job_type,
                "prompt": job.prompt,
                "request_payload": job.request_payload,
                "boot_state": boot_state,
                "login_state": login_state,
                "artifacts": [asdict(artifact) for artifact in local_artifacts],
            },
        )
        local_artifacts.append(_local_artifact("metadata", metadata_path, "application/json", {}))
        with _lock:
            job.artifacts = local_artifacts
            job.status = "completed"
            job.result_payload = {
                "artifact_count": len(local_artifacts),
                "artifacts_dir": ensure_job_directories(job.id)["artifacts"],
            }
            job.finished_at = _now_iso()
    except ProviderAutomationError as exc:
        local_artifacts = _persist_artifacts(job.id, exc.artifacts)
        error_path = write_job_metadata_artifact(
            job.id,
            "local-agent-error.json",
            {
                "job_id": job.id,
                "error_code": exc.code,
                "error_message": exc.message,
                "artifacts": [asdict(artifact) for artifact in local_artifacts],
            },
        )
        local_artifacts.append(_local_artifact("metadata", error_path, "application/json", {}))
        with _lock:
            job.artifacts = local_artifacts
            job.status = "failed"
            job.error_code = exc.code
            job.error_message = exc.message
            job.finished_at = _now_iso()
    except Exception as exc:
        error_path = write_job_metadata_artifact(
            job.id,
            "local-agent-error.json",
            {
                "job_id": job.id,
                "error_code": "LOCAL_AGENT_ERROR",
                "error_message": str(exc),
            },
        )
        with _lock:
            job.artifacts = [_local_artifact("metadata", error_path, "application/json", {})]
            job.status = "failed"
            job.error_code = "LOCAL_AGENT_ERROR"
            job.error_message = str(exc)
            job.finished_at = _now_iso()
    finally:
        if runtime is not None:
            runtime.close()


def _build_context(
    *,
    job_id: str,
    profile_id: str,
    profile_name: str,
    job_type: str,
    prompt: str,
    request_payload: dict[str, Any],
    headless: bool,
) -> ProviderExecutionContext:
    profile_dirs = ensure_profile_directories(profile_id)
    job_dirs = ensure_job_directories(job_id)
    storage_state_path = Path(profile_dirs["browser"]) / "storage_state.json"
    normalized_cookie_path = Path(profile_dirs["cookies"]) / "normalized_cookies.json"
    local_request_payload = dict(request_payload)
    local_request_payload.pop("provider_mode", None)
    return ProviderExecutionContext(
        job_id=job_id,
        profile_id=profile_id,
        profile_name=profile_name,
        provider="grok",
        job_type=job_type,
        prompt=prompt,
        request_payload=local_request_payload,
        headless=headless,
        artifacts_dir=job_dirs["artifacts"],
        logs_dir=job_dirs["logs"],
        browser_dir=profile_dirs["browser"],
        cache_dir=profile_dirs["cache"],
        storage_state_path=str(storage_state_path) if storage_state_path.exists() else None,
        normalized_cookie_path=str(normalized_cookie_path) if normalized_cookie_path.exists() else None,
        runtime_settings={
            "headless": headless,
            "timeout_ms": int(os.getenv("FLOWGROK_LOCAL_TIMEOUT_MS", "120000")),
            "navigation_timeout_ms": int(os.getenv("FLOWGROK_LOCAL_NAVIGATION_TIMEOUT_MS", "60000")),
        },
        antidetect_settings=None,
    )


def _persist_artifacts(job_id: str, artifacts: list[ProviderArtifact]) -> list[LocalArtifact]:
    persisted: list[LocalArtifact] = []
    for artifact in artifacts:
        if artifact.binary_content is not None:
            path = write_job_binary_artifact(job_id, artifact.file_name, artifact.binary_content)
        else:
            path = write_job_text_artifact(job_id, artifact.file_name, artifact.text_content or "")
        persisted.append(_local_artifact(artifact.artifact_type, path, artifact.mime_type, artifact.metadata))
    return persisted


def _local_artifact(
    artifact_type: str,
    file_path: str,
    mime_type: str,
    metadata: dict[str, Any],
) -> LocalArtifact:
    path = Path(file_path)
    return LocalArtifact(
        id=path.stem,
        artifact_type=artifact_type,
        file_path=str(path),
        mime_type=mime_type,
        size_bytes=path.stat().st_size if path.exists() else 0,
        created_at=_now_iso(),
        metadata=metadata,
    )


def _get_job(job_id: str) -> LocalJob:
    with _lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _job_response(job: LocalJob) -> dict[str, object]:
    payload = asdict(job)
    payload["artifacts"] = [asdict(artifact) for artifact in job.artifacts]
    return payload


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
