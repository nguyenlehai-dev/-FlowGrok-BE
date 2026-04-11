from pydantic import BaseModel, Field
from typing import Optional, Any, Literal
from datetime import datetime

# Proxy Schemas
class ProxyBase(BaseModel):
    ip: str
    port: int
    protocol: str = "http"
    username: Optional[str] = None
    password: Optional[str] = None
    country: Optional[str] = None
    provider: Optional[str] = None

class ProxyCreate(ProxyBase):
    pass

class ProxyUpdate(BaseModel):
    ip: Optional[str] = None
    port: Optional[int] = None
    protocol: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    country: Optional[str] = None
    provider: Optional[str] = None
    is_active: Optional[bool] = None

class ProxyResponse(ProxyBase):
    id: str
    status: str
    latency_ms: Optional[int] = None
    fail_count: int
    is_active: bool
    last_checked_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

# Profile Schemas
class ProfileBase(BaseModel):
    name: str
    category: Literal["grok", "flow", "dreamina"]
    proxy_id: Optional[str] = None
    description: Optional[str] = None
    cookies_json: Optional[str] = None
    antidetect_settings: Optional[Any] = None
    headless: bool = True
    concurrency_limit: int = Field(default=1, ge=1)
    provider_config: Optional[Any] = None
    is_enabled: bool = True

class ProfileCreate(ProfileBase):
    user_id: Optional[str] = None

class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[Literal["grok", "flow", "dreamina"]] = None
    proxy_id: Optional[str] = None
    cookies_json: Optional[str] = None
    antidetect_settings: Optional[Any] = None
    headless: Optional[bool] = None
    concurrency_limit: Optional[int] = Field(default=None, ge=1)
    provider_config: Optional[Any] = None
    is_enabled: Optional[bool] = None
    status: Optional[str] = None

class ProfileResponse(ProfileBase):
    id: str
    status: str
    cookie_source_type: Optional[str] = None
    cookie_import_name: Optional[str] = None
    cookie_imported_at: Optional[datetime] = None
    storage_path: Optional[str] = None
    cache_path: Optional[str] = None
    last_used_at: Optional[datetime] = None
    last_health_check_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class ProfileRuntimeSettingsBase(BaseModel):
    browser_type: str = "chromium"
    channel: Optional[str] = None
    cdp_url: Optional[str] = None
    headless: bool = True
    timeout_ms: int = 120000
    navigation_timeout_ms: int = 60000
    max_retries: int = 2
    concurrency_limit: int = Field(default=1, ge=1)
    launch_args: Optional[Any] = None


class ProfileRuntimeSettingsUpsert(ProfileRuntimeSettingsBase):
    pass


class ProfileRuntimeSettingsResponse(ProfileRuntimeSettingsBase):
    id: str
    profile_id: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ProfileAntidetectSettingsBase(BaseModel):
    user_agent: Optional[str] = None
    viewport_width: Optional[int] = None
    viewport_height: Optional[int] = None
    timezone: Optional[str] = None
    locale: Optional[str] = None
    platform: Optional[str] = None
    webrtc_mode: str = "default"
    canvas_mode: str = "default"
    webgl_vendor: Optional[str] = None
    hardware_concurrency: Optional[int] = None
    device_memory: Optional[int] = None


class ProfileAntidetectSettingsUpsert(ProfileAntidetectSettingsBase):
    pass


class ProfileAntidetectSettingsResponse(ProfileAntidetectSettingsBase):
    id: str
    profile_id: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ProfileCookieImportResponse(BaseModel):
    id: str
    profile_id: str
    source_type: str
    file_name: Optional[str] = None
    raw_content_path: Optional[str] = None
    parsed_count: int
    valid_count: int
    invalid_count: int
    import_status: str
    error_message: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class JobCreate(BaseModel):
    profile_id: str
    job_type: Literal["generate_image", "generate_video"]
    prompt: str
    # request_payload for generate_video supports:
    # {
    #   "video_resolution": "480p" | "720p",   (optional, default: 480p)
    #   "video_duration": "6s" | "10s",        (optional, default: 6s)
    #   "source_image": {                      (optional, set automatically by upload endpoint)
    #     "file_path": "/abs/path/to/image",
    #     "mime_type": "image/png"
    #   }
    # }
    request_payload: Optional[Any] = None
    priority: int = 100


class JobResponse(BaseModel):
    id: str
    requested_by_user_id: Optional[str] = None
    api_key_id: Optional[str] = None
    profile_id: str
    prompt: str
    category: str
    provider: Optional[str] = None
    job_type: Optional[str] = None
    request_payload: Optional[Any] = None
    status: str
    priority: int
    retry_count: int
    worker_id: Optional[str] = None
    proxy_snapshot: Optional[Any] = None
    browser_session_path: Optional[str] = None
    result_url: Optional[str] = None
    result_payload: Optional[Any] = None
    error_logs: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class JobArtifactResponse(BaseModel):
    id: str
    job_id: str
    artifact_type: str
    file_path: str
    public_url: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True
