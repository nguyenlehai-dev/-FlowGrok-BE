from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import ApiClientContext, get_api_client_context, get_current_user, require_internal_worker
from app.db.database import get_db
from app.models.core import Job, JobArtifact, Profile, User
from app.schemas.core import JobCreate, JobResponse, JobArtifactResponse
from app.schemas.jobs_internal import (
    InternalJobArtifactCreate,
    InternalJobClaimRequest,
    InternalWorkerRunOnceRequest,
    InternalWorkerRunOnceResponse,
    InternalJobStatusUpdate,
    InternalWorkerHeartbeat,
)
from app.worker.job_runner import JobRunner, WorkerRuntimeConfig

router = APIRouter()
internal_router = APIRouter()
external_router = APIRouter()


@router.post("/", response_model=JobResponse)
def create_job(payload: JobCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.id == payload.profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    if not profile.is_enabled:
        raise HTTPException(status_code=400, detail="Profile is disabled")

    running_count = db.query(Job).filter(
        Job.profile_id == profile.id,
        Job.status.in_(["queued", "reserved", "booting_browser", "logging_in", "running"])
    ).count()
    if running_count >= (profile.concurrency_limit or 1):
        raise HTTPException(status_code=400, detail="Profile concurrency limit reached")

    job = Job(
        requested_by_user_id=current_user.id,
        profile_id=profile.id,
        prompt=payload.prompt,
        category=profile.category,
        provider=profile.category,
        job_type=payload.job_type,
        request_payload=payload.request_payload,
        priority=payload.priority,
        status="queued",
        browser_session_path=profile.storage_path,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@router.get("/", response_model=list[JobResponse])
def list_jobs(
    status: str | None = None,
    provider: str | None = None,
    job_type: str | None = None,
    profile_id: str | None = None,
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Job).filter(Job.requested_by_user_id == current_user.id)
    if status:
        query = query.filter(Job.status == status)
    if provider:
        query = query.filter(Job.provider == provider)
    if job_type:
        query = query.filter(Job.job_type == job_type)
    if profile_id:
        query = query.filter(Job.profile_id == profile_id)
    return query.order_by(Job.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id, Job.requested_by_user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/{job_id}/cancel", response_model=JobResponse)
def cancel_job(job_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id, Job.requested_by_user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in {"queued", "reserved", "booting_browser", "logging_in", "running"}:
        raise HTTPException(status_code=400, detail="Job can no longer be cancelled")
    job.status = "cancelled"
    db.commit()
    db.refresh(job)
    return job


@router.get("/{job_id}/artifacts", response_model=list[JobArtifactResponse])
def list_job_artifacts(job_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id, Job.requested_by_user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return db.query(JobArtifact).filter(JobArtifact.job_id == job.id).all()


@router.post("/run-worker-once", response_model=InternalWorkerRunOnceResponse)
def run_worker_once_for_dashboard(
    payload: InternalWorkerRunOnceRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    runner = JobRunner(
        WorkerRuntimeConfig(
            worker_id=payload.worker_id,
            max_concurrency=1,
            headless=True,
            max_priority=payload.max_priority,
        )
    )
    result = runner.run_once(db)
    return InternalWorkerRunOnceResponse(**result)


@external_router.post("/", response_model=JobResponse)
def create_client_job(
    payload: JobCreate,
    client: ApiClientContext = Depends(get_api_client_context),
    db: Session = Depends(get_db),
):
    profile = db.query(Profile).filter(
        Profile.id == payload.profile_id,
        Profile.user_id == client.user.id,
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    if not profile.is_enabled:
        raise HTTPException(status_code=400, detail="Profile is disabled")

    running_count = db.query(Job).filter(
        Job.profile_id == profile.id,
        Job.status.in_(["queued", "reserved", "booting_browser", "logging_in", "running", "uploading_result"]),
    ).count()
    if running_count >= (profile.concurrency_limit or 1):
        raise HTTPException(status_code=400, detail="Profile concurrency limit reached")

    job = Job(
        requested_by_user_id=client.user.id,
        api_key_id=client.api_key.id,
        profile_id=profile.id,
        prompt=payload.prompt,
        category=profile.category,
        provider=profile.category,
        job_type=payload.job_type,
        request_payload=payload.request_payload,
        priority=payload.priority,
        status="queued",
        browser_session_path=profile.storage_path,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@external_router.get("/", response_model=list[JobResponse])
def list_client_jobs(
    status: str | None = None,
    provider: str | None = None,
    job_type: str | None = None,
    profile_id: str | None = None,
    skip: int = 0,
    limit: int = 100,
    client: ApiClientContext = Depends(get_api_client_context),
    db: Session = Depends(get_db),
):
    query = db.query(Job).filter(Job.requested_by_user_id == client.user.id)
    if status:
        query = query.filter(Job.status == status)
    if provider:
        query = query.filter(Job.provider == provider)
    if job_type:
        query = query.filter(Job.job_type == job_type)
    if profile_id:
        query = query.filter(Job.profile_id == profile_id)
    return query.order_by(Job.created_at.desc()).offset(skip).limit(limit).all()


@external_router.get("/{job_id}", response_model=JobResponse)
def get_client_job(
    job_id: str,
    client: ApiClientContext = Depends(get_api_client_context),
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.id == job_id, Job.requested_by_user_id == client.user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@external_router.get("/{job_id}/artifacts", response_model=list[JobArtifactResponse])
def list_client_job_artifacts(
    job_id: str,
    client: ApiClientContext = Depends(get_api_client_context),
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.id == job_id, Job.requested_by_user_id == client.user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return db.query(JobArtifact).filter(JobArtifact.job_id == job.id).all()


@internal_router.post("/claim", response_model=JobResponse | None)
def claim_next_job(
    payload: InternalJobClaimRequest,
    _worker_token: str = Depends(require_internal_worker),
    db: Session = Depends(get_db),
):
    query = db.query(Job).filter(Job.status == "queued", Job.priority <= payload.max_priority).order_by(Job.priority.asc(), Job.created_at.asc())
    job = query.first()
    if not job:
        return None
    job.status = "reserved"
    job.worker_id = payload.worker_id
    job.started_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    return job


@internal_router.post("/{job_id}/heartbeat")
def job_heartbeat(
    job_id: str,
    payload: InternalWorkerHeartbeat,
    _worker_token: str = Depends(require_internal_worker),
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.worker_id and job.worker_id != payload.worker_id:
        raise HTTPException(status_code=409, detail="Job belongs to another worker")
    job.worker_id = payload.worker_id
    db.commit()
    return {"status": "success", "job_id": job_id, "worker_id": payload.worker_id, "timestamp": payload.timestamp.isoformat()}


@internal_router.post("/{job_id}/status", response_model=JobResponse)
def update_job_status(
    job_id: str,
    payload: InternalJobStatusUpdate,
    _worker_token: str = Depends(require_internal_worker),
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.worker_id and job.worker_id != payload.worker_id:
        raise HTTPException(status_code=409, detail="Job belongs to another worker")

    job.worker_id = payload.worker_id
    job.status = payload.status
    job.error_logs = payload.error_logs
    job.result_payload = payload.result_payload
    job.result_url = payload.result_url
    if payload.status in {"running", "logging_in", "booting_browser", "uploading_result"} and not job.started_at:
        job.started_at = datetime.now(timezone.utc)
    if payload.status in {"completed", "failed", "cancelled"}:
        job.finished_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    return job


@internal_router.post("/{job_id}/artifacts", response_model=JobArtifactResponse)
def register_job_artifact(
    job_id: str,
    payload: InternalJobArtifactCreate,
    _worker_token: str = Depends(require_internal_worker),
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.worker_id and job.worker_id != payload.worker_id:
        raise HTTPException(status_code=409, detail="Job belongs to another worker")

    artifact = JobArtifact(
        job_id=job.id,
        artifact_type=payload.artifact_type,
        file_path=payload.file_path,
        public_url=payload.public_url,
        mime_type=payload.mime_type,
        size_bytes=payload.size_bytes,
    )
    db.add(artifact)
    db.commit()
    db.refresh(artifact)
    return artifact


@internal_router.post("/run-once", response_model=InternalWorkerRunOnceResponse)
def worker_run_once(
    payload: InternalWorkerRunOnceRequest,
    _worker_token: str = Depends(require_internal_worker),
    db: Session = Depends(get_db),
):
    runner = JobRunner(
        WorkerRuntimeConfig(
            worker_id=payload.worker_id,
            max_concurrency=1,
            headless=True,
            max_priority=payload.max_priority,
        )
    )
    result = runner.run_once(db)
    return InternalWorkerRunOnceResponse(**result)
