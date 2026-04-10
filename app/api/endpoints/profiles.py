import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.deps import ApiClientContext, get_api_client_context, get_current_user
from app.db.database import get_db
from app.models.core import Profile, ProfileAntidetectSettings, ProfileCookieImport, ProfileRuntimeSettings, User
from app.schemas.core import (
    ProfileAntidetectSettingsResponse,
    ProfileAntidetectSettingsUpsert,
    ProfileCookieImportResponse,
    ProfileCreate,
    ProfileResponse,
    ProfileRuntimeSettingsResponse,
    ProfileRuntimeSettingsUpsert,
    ProfileUpdate,
)
from app.services.cookie_import import parse_json_cookie_payload, parse_storage_state_payload, parse_txt_cookie_payload, validate_profile_cookies
from app.services.profile_storage import ensure_profile_directories, save_cookie_upload, save_normalized_cookie_state, save_storage_state
from app.worker.providers import get_provider_automation
from app.worker.providers.base import ProviderAutomationError, ProviderExecutionContext

router = APIRouter()
external_router = APIRouter()

@router.post("/", response_model=ProfileResponse)
def create_profile(profile: ProfileCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    directories = ensure_profile_directories("tmp")
    payload = profile.model_dump(exclude={"user_id"})
    payload["headless"] = True
    db_profile = Profile(**payload, user_id=current_user.id)
    db.add(db_profile)
    db.commit()
    db.refresh(db_profile)
    directories = ensure_profile_directories(db_profile.id)
    db_profile.storage_path = directories["browser"]
    db_profile.cache_path = directories["cache"]
    db.add(ProfileRuntimeSettings(profile_id=db_profile.id, headless=db_profile.headless, concurrency_limit=db_profile.concurrency_limit))
    db.add(ProfileAntidetectSettings(profile_id=db_profile.id))
    db.commit()
    db.refresh(db_profile)
    return db_profile

@router.get("/", response_model=list[ProfileResponse])
def get_profiles(
    category: str | None = None,
    status: str | None = None,
    proxy_id: str | None = None,
    search: str | None = None,
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Profile).filter(Profile.user_id == current_user.id)
    if category:
        query = query.filter(Profile.category == category)
    if status:
        query = query.filter(Profile.status == status)
    if proxy_id:
        query = query.filter(Profile.proxy_id == proxy_id)
    if search:
        query = query.filter(Profile.name.ilike(f"%{search}%"))
    return query.order_by(Profile.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/{profile_id}", response_model=ProfileResponse)
def get_profile(profile_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.id == profile_id, Profile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.patch("/{profile_id}", response_model=ProfileResponse)
def update_profile(profile_id: str, payload: ProfileUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.id == profile_id, Profile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key == "headless":
            value = True
        setattr(profile, key, value)
    profile.headless = True
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/{profile_id}/runtime-settings", response_model=ProfileRuntimeSettingsResponse)
def get_runtime_settings(profile_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.id == profile_id, Profile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    runtime = db.query(ProfileRuntimeSettings).filter(ProfileRuntimeSettings.profile_id == profile.id).first()
    if not runtime:
        runtime = ProfileRuntimeSettings(profile_id=profile.id, headless=profile.headless, concurrency_limit=profile.concurrency_limit)
        db.add(runtime)
        db.commit()
        db.refresh(runtime)
    return runtime


@router.put("/{profile_id}/runtime-settings", response_model=ProfileRuntimeSettingsResponse)
def upsert_runtime_settings(profile_id: str, payload: ProfileRuntimeSettingsUpsert, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.id == profile_id, Profile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    runtime = db.query(ProfileRuntimeSettings).filter(ProfileRuntimeSettings.profile_id == profile.id).first()
    if not runtime:
        runtime = ProfileRuntimeSettings(profile_id=profile.id)
        db.add(runtime)
    runtime_payload = payload.model_dump()
    runtime_payload["headless"] = True
    for key, value in runtime_payload.items():
        setattr(runtime, key, value)
    runtime.headless = True
    profile.headless = True
    profile.concurrency_limit = runtime.concurrency_limit
    db.commit()
    db.refresh(runtime)
    return runtime


@router.get("/{profile_id}/antidetect-settings", response_model=ProfileAntidetectSettingsResponse)
def get_antidetect_settings(profile_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.id == profile_id, Profile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    settings = db.query(ProfileAntidetectSettings).filter(ProfileAntidetectSettings.profile_id == profile.id).first()
    if not settings:
        settings = ProfileAntidetectSettings(profile_id=profile.id)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


@router.put("/{profile_id}/antidetect-settings", response_model=ProfileAntidetectSettingsResponse)
def upsert_antidetect_settings(profile_id: str, payload: ProfileAntidetectSettingsUpsert, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.id == profile_id, Profile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    settings = db.query(ProfileAntidetectSettings).filter(ProfileAntidetectSettings.profile_id == profile.id).first()
    if not settings:
        settings = ProfileAntidetectSettings(profile_id=profile.id)
        db.add(settings)
    for key, value in payload.model_dump().items():
        setattr(settings, key, value)
    profile.antidetect_settings = payload.model_dump()
    db.commit()
    db.refresh(settings)
    return settings


@router.post("/{profile_id}/cookies/import", response_model=ProfileCookieImportResponse)
async def import_cookies(profile_id: str, source_type: str = Form(...), file: UploadFile = File(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if source_type not in {"txt", "json", "storage_state_json", "manual"}:
        raise HTTPException(status_code=400, detail="Unsupported source_type")
    profile = db.query(Profile).filter(Profile.id == profile_id, Profile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    raw_path, raw_text = await save_cookie_upload(profile.id, file)
    parsed_count = 0
    valid_count = 0
    invalid_count = 0
    error_message = None
    import_status = "success"
    normalized_payload = "[]"
    result_message = ""

    try:
        if source_type == "json":
            result = parse_json_cookie_payload(raw_text, profile.category)
        elif source_type == "storage_state_json":
            result = parse_storage_state_payload(raw_text, profile.category)
        else:
            result = parse_txt_cookie_payload(raw_text, profile.category)
        parsed_count = result.parsed_count
        valid_count = result.valid_count
        invalid_count = result.invalid_count
        result_message = result.message
        normalized_payload = json.dumps(result.normalized_cookies)
    except Exception as exc:
        import_status = "failed"
        invalid_count = parsed_count or 1
        error_message = str(exc)

    cookie_import = ProfileCookieImport(
        profile_id=profile.id,
        source_type=source_type,
        file_name=file.filename,
        raw_content_path=raw_path,
        parsed_count=parsed_count,
        valid_count=valid_count,
        invalid_count=invalid_count,
        import_status=import_status,
        error_message=error_message or result_message,
    )
    db.add(cookie_import)

    if import_status == "success" and valid_count > 0:
        state_paths = save_storage_state(profile.id, normalized_payload, result.storage_state) if source_type == "storage_state_json" and result.storage_state else save_normalized_cookie_state(profile.id, normalized_payload)
        profile.cookies_json = normalized_payload
        profile.cookie_source_type = source_type
        profile.cookie_import_name = file.filename
        profile.cookie_imported_at = datetime.now(timezone.utc)
        profile.status = "idle"
        profile.provider_config = {
            **(profile.provider_config or {}),
            "normalized_cookie_path": state_paths["normalized_cookie_path"],
            "storage_state_path": state_paths["storage_state_path"],
        }
    elif import_status == "success":
        profile.status = "cookie_dead"

    db.commit()
    db.refresh(cookie_import)
    return cookie_import


@router.get("/{profile_id}/cookie-imports", response_model=list[ProfileCookieImportResponse])
def list_cookie_imports(profile_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.id == profile_id, Profile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return db.query(ProfileCookieImport).filter(ProfileCookieImport.profile_id == profile.id).order_by(ProfileCookieImport.created_at.desc()).all()


@router.post("/{profile_id}/test-login")
def test_profile_login(profile_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.id == profile_id, Profile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    validation = validate_profile_cookies(profile.category, profile.cookies_json)
    runtime = db.query(ProfileRuntimeSettings).filter(ProfileRuntimeSettings.profile_id == profile.id).first()
    antidetect = db.query(ProfileAntidetectSettings).filter(ProfileAntidetectSettings.profile_id == profile.id).first()
    directories = ensure_profile_directories(profile.id)
    provider_config = profile.provider_config or {}
    execution_context = ProviderExecutionContext(
        job_id=f"test-login-{profile.id}",
        profile_id=profile.id,
        profile_name=profile.name,
        provider=profile.category,
        job_type="test_login",
        prompt="",
        request_payload={},
        headless=runtime.headless if runtime else profile.headless,
        artifacts_dir=directories["browser"],
        logs_dir=directories["browser"],
        browser_dir=directories["browser"],
        cache_dir=directories["cache"],
        storage_state_path=provider_config.get("storage_state_path"),
        normalized_cookie_path=provider_config.get("normalized_cookie_path"),
        runtime_settings=_serialize_sqla_model(runtime),
        antidetect_settings=_serialize_sqla_model(antidetect),
    )

    provider_runtime = None
    try:
        provider_runtime = get_provider_automation(execution_context)
        provider_runtime.bootstrap_context()
        cookie_state = provider_runtime.validate_cookies()
        login_state = provider_runtime.login_with_cookies()
        valid = bool(login_state.get("looks_logged_in", validation["valid"]))
        profile.status = "idle" if valid else "cookie_dead"
        if valid:
            profile.last_health_check_at = datetime.now(timezone.utc)
        db.commit()
        return {
            "status": "success",
            "provider": profile.category,
            "valid": valid,
            "parsed_count": validation["parsed_count"],
            "valid_count": validation["valid_count"],
            "invalid_count": validation["invalid_count"],
            "message": validation["message"],
            "cookie_state": cookie_state,
            "login_state": login_state,
        }
    except ProviderAutomationError as exc:
        profile.status = "cookie_dead" if exc.code == "COOKIE_INVALID" else "error"
        db.commit()
        return {
            "status": "error",
            "provider": profile.category,
            "valid": False,
            "parsed_count": validation["parsed_count"],
            "valid_count": validation["valid_count"],
            "invalid_count": validation["invalid_count"],
            "message": exc.message,
            "error_code": exc.code,
        }
    except Exception as exc:
        profile.status = "error"
        db.commit()
        return {
            "status": "error",
            "provider": profile.category,
            "valid": False,
            "parsed_count": validation["parsed_count"],
            "valid_count": validation["valid_count"],
            "invalid_count": validation["invalid_count"],
            "message": str(exc),
            "error_code": "TEST_LOGIN_FAILED",
        }
    finally:
        if provider_runtime is not None:
            provider_runtime.close()

@router.delete("/{profile_id}")
def delete_profile(profile_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.id == profile_id, Profile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    db.delete(profile)
    db.commit()
    return {"status": "success", "message": "Profile deleted"}


@external_router.get("/", response_model=list[ProfileResponse])
def list_client_profiles(
    category: str | None = None,
    status: str | None = None,
    search: str | None = None,
    skip: int = 0,
    limit: int = 100,
    client: ApiClientContext = Depends(get_api_client_context),
    db: Session = Depends(get_db),
):
    query = db.query(Profile).filter(Profile.user_id == client.user.id, Profile.is_enabled.is_(True))
    if category:
        query = query.filter(Profile.category == category)
    if status:
        query = query.filter(Profile.status == status)
    if search:
        query = query.filter(Profile.name.ilike(f"%{search}%"))
    return query.order_by(Profile.created_at.desc()).offset(skip).limit(limit).all()


def _serialize_sqla_model(model: object | None) -> dict[str, object] | None:
    if model is None or not hasattr(model, "__table__"):
        return None
    data: dict[str, object] = {}
    for column in model.__table__.columns:  # type: ignore[attr-defined]
        value = getattr(model, column.name)
        if isinstance(value, datetime):
            data[column.name] = value.isoformat()
        else:
            data[column.name] = value
    return data
