import uuid
import datetime
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Text, JSON
from app.db.base import Base

def generate_uuid():
    return str(uuid.uuid4())

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=generate_uuid)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="user") # admin, user
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc))

class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"))
    key = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True)
    key_hash = Column(String, nullable=True)
    key_preview = Column(String, nullable=True)
    status = Column(String, default="active") # active, revoked
    rate_limit_per_minute = Column(Integer, default=60)
    last_used_at = Column(DateTime, nullable=True)
    last_used_ip = Column(String, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc))

class Proxy(Base):
    __tablename__ = "proxies"

    id = Column(String, primary_key=True, default=generate_uuid)
    ip = Column(String, nullable=False)
    port = Column(Integer, nullable=False)
    protocol = Column(String, default="http")
    username = Column(String, nullable=True)
    password = Column(String, nullable=True)
    country = Column(String, nullable=True)
    provider = Column(String, nullable=True)
    status = Column(String, default="alive") # alive, dead
    latency_ms = Column(Integer, nullable=True)
    fail_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    last_checked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc))

class Profile(Base):
    __tablename__ = "profiles"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", name="fk_profile_user_id"), nullable=True)
    proxy_id = Column(String, ForeignKey("proxies.id", name="fk_profile_proxy_id"), nullable=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String, nullable=False) # grok, flow, dreamina
    cookies_json = Column(Text, nullable=True)
    antidetect_settings = Column(JSON, nullable=True)
    cookie_source_type = Column(String, nullable=True)
    cookie_import_name = Column(String, nullable=True)
    cookie_imported_at = Column(DateTime, nullable=True)
    storage_path = Column(String, nullable=True)
    cache_path = Column(String, nullable=True)
    headless = Column(Boolean, default=True)
    concurrency_limit = Column(Integer, default=1)
    provider_config = Column(JSON, nullable=True)
    status = Column(String, default="idle") # idle, running, cookie_dead, error
    last_used_at = Column(DateTime, nullable=True)
    last_health_check_at = Column(DateTime, nullable=True)
    is_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc))


class ProfileAntidetectSettings(Base):
    __tablename__ = "profile_antidetect_settings"

    id = Column(String, primary_key=True, default=generate_uuid)
    profile_id = Column(String, ForeignKey("profiles.id", name="fk_antidetect_profile_id"), unique=True, nullable=False)
    user_agent = Column(String, nullable=True)
    viewport_width = Column(Integer, nullable=True)
    viewport_height = Column(Integer, nullable=True)
    timezone = Column(String, nullable=True)
    locale = Column(String, nullable=True)
    platform = Column(String, nullable=True)
    webrtc_mode = Column(String, default="default")
    canvas_mode = Column(String, default="default")
    webgl_vendor = Column(String, nullable=True)
    hardware_concurrency = Column(Integer, nullable=True)
    device_memory = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc))


class ProfileRuntimeSettings(Base):
    __tablename__ = "profile_runtime_settings"

    id = Column(String, primary_key=True, default=generate_uuid)
    profile_id = Column(String, ForeignKey("profiles.id", name="fk_runtime_profile_id"), unique=True, nullable=False)
    browser_type = Column(String, default="chromium")
    channel = Column(String, nullable=True)
    headless = Column(Boolean, default=True)
    timeout_ms = Column(Integer, default=120000)
    navigation_timeout_ms = Column(Integer, default=60000)
    max_retries = Column(Integer, default=2)
    concurrency_limit = Column(Integer, default=1)
    launch_args = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc))


class ProfileCookieImport(Base):
    __tablename__ = "profile_cookie_imports"

    id = Column(String, primary_key=True, default=generate_uuid)
    profile_id = Column(String, ForeignKey("profiles.id", name="fk_cookie_import_profile_id"), nullable=False)
    source_type = Column(String, nullable=False)
    file_name = Column(String, nullable=True)
    raw_content_path = Column(String, nullable=True)
    parsed_count = Column(Integer, default=0)
    valid_count = Column(Integer, default=0)
    invalid_count = Column(Integer, default=0)
    import_status = Column(String, default="pending")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

class Job(Base):
    __tablename__ = "generation_jobs"

    id = Column(String, primary_key=True, default=generate_uuid)
    requested_by_user_id = Column(String, ForeignKey("users.id"), nullable=True)
    api_key_id = Column(String, ForeignKey("api_keys.id"), nullable=True)
    profile_id = Column(String, ForeignKey("profiles.id", name="fk_job_profile_id"))
    prompt = Column(Text, nullable=False)
    category = Column(String, nullable=False)
    provider = Column(String, nullable=True)
    job_type = Column(String, nullable=True)
    request_payload = Column(JSON, nullable=True)
    status = Column(String, default="queued") # queued, running, completed, failed
    priority = Column(Integer, default=100)
    retry_count = Column(Integer, default=0)
    worker_id = Column(String, nullable=True)
    proxy_snapshot = Column(JSON, nullable=True)
    browser_session_path = Column(String, nullable=True)
    result_url = Column(String, nullable=True)
    result_payload = Column(JSON, nullable=True)
    error_logs = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc))


class JobArtifact(Base):
    __tablename__ = "job_artifacts"

    id = Column(String, primary_key=True, default=generate_uuid)
    job_id = Column(String, ForeignKey("generation_jobs.id", name="fk_artifact_job_id"), nullable=False)
    artifact_type = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    public_url = Column(String, nullable=True)
    mime_type = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
