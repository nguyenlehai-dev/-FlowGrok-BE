import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.core.security import check_rate_limit, decode_access_token, hash_api_key, verify_api_key, verify_worker_token
from app.models.core import User, ApiKey

# Sử dụng HTTPBearer scheme cho Swagger UI hiển thị ổ khóa
bearer_scheme = HTTPBearer(auto_error=False)
logger = logging.getLogger("flowgrok.security")


@dataclass
class ApiClientContext:
    user: User
    api_key: ApiKey


def _get_client_ip(request: Request | None) -> str:
    if request is None:
        return "unknown"
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _find_active_api_key(db: Session, presented_key: str) -> ApiKey | None:
    candidates = db.query(ApiKey).filter(ApiKey.status == "active").all()
    for item in candidates:
        if verify_api_key(presented_key, item.key_hash):
            return item
        if item.key and item.key == presented_key:
            item.key_hash = hash_api_key(presented_key)
            return item
    return None


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Dependency: Xác thực JWT Bearer token và trả về User object."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
        )
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return user


def get_current_user_by_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Dependency: Xác thực bằng API Key (X-API-Key header) HOẶC JWT Bearer token.
    Ưu tiên kiểm tra API Key trước, nếu không có thì fallback sang JWT."""
    if credentials:
        # Thử tìm trong bảng API Keys trước
        api_key_record = _find_active_api_key(db, credentials.credentials)
        if api_key_record:
            user = db.query(User).filter(User.id == api_key_record.user_id).first()
            if user:
                return user

        # Fallback: thử decode JWT
        payload = decode_access_token(credentials.credentials)
        if payload:
            user_id = payload.get("sub")
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
    )


def get_api_client_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
    request: Request = None,
) -> ApiClientContext:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
        )

    api_key_record = _find_active_api_key(db, credentials.credentials)
    if not api_key_record:
        logger.warning("api_key_auth_failed ip=%s reason=invalid_key", _get_client_ip(request))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    if api_key_record.expires_at and api_key_record.expires_at <= datetime.now(timezone.utc):
        logger.warning("api_key_auth_failed ip=%s key_id=%s reason=expired", _get_client_ip(request), api_key_record.id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key expired",
        )

    user = db.query(User).filter(User.id == api_key_record.user_id).first()
    if user is None or not user.is_active:
        logger.warning("api_key_auth_failed ip=%s key_id=%s reason=user_not_found", _get_client_ip(request), api_key_record.id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    rate_limit = api_key_record.rate_limit_per_minute or 60
    rate_key = f"api_key:{api_key_record.id}"
    if not check_rate_limit(rate_key, rate_limit):
        logger.warning(
            "api_key_rate_limited ip=%s key_id=%s limit=%s",
            _get_client_ip(request),
            api_key_record.id,
            rate_limit,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="API key rate limit exceeded",
        )

    api_key_record.last_used_at = datetime.now(timezone.utc)
    api_key_record.last_used_ip = _get_client_ip(request)
    db.commit()
    db.refresh(api_key_record)
    logger.info("api_key_auth_success ip=%s key_id=%s user_id=%s", api_key_record.last_used_ip, api_key_record.id, user.id)
    return ApiClientContext(user=user, api_key=api_key_record)


def require_internal_worker(
    x_worker_token: str | None = Header(default=None),
    request: Request = None,
) -> str:
    client_ip = _get_client_ip(request)
    if not x_worker_token:
        logger.warning("worker_auth_failed ip=%s reason=missing_token", client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing worker token",
        )
    if not verify_worker_token(x_worker_token):
        logger.warning("worker_auth_failed ip=%s reason=invalid_token", client_ip)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid worker token",
        )
    if not check_rate_limit(f"worker:{client_ip}", 240):
        logger.warning("worker_rate_limited ip=%s", client_ip)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Worker rate limit exceeded",
        )
    logger.info("worker_auth_success ip=%s", client_ip)
    return x_worker_token
