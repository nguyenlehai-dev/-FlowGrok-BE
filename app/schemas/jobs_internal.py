from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class InternalJobClaimRequest(BaseModel):
    worker_id: str
    max_priority: int = 100


class InternalJobStatusUpdate(BaseModel):
    worker_id: str
    status: str
    error_logs: Optional[str] = None
    result_payload: Optional[Any] = None
    result_url: Optional[str] = None


class InternalJobArtifactCreate(BaseModel):
    worker_id: str
    artifact_type: str
    file_path: str
    public_url: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None


class InternalWorkerHeartbeat(BaseModel):
    worker_id: str
    timestamp: datetime


class InternalWorkerRunOnceRequest(BaseModel):
    worker_id: str
    max_priority: int = 100


class InternalWorkerRunOnceResponse(BaseModel):
    worker_id: str
    status: str
    job_id: Optional[str] = None
    detail: Optional[str] = None
