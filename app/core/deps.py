from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.core.security import decode_access_token
from app.models.core import User, ApiKey

# Sử dụng HTTPBearer scheme cho Swagger UI hiển thị ổ khóa
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class ApiClientContext:
    user: User
    api_key: ApiKey


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
        api_key_record = db.query(ApiKey).filter(
            ApiKey.key == credentials.credentials,
            ApiKey.status == "active",
        ).first()
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
) -> ApiClientContext:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
        )

    api_key_record = db.query(ApiKey).filter(
        ApiKey.key == credentials.credentials,
        ApiKey.status == "active",
    ).first()
    if not api_key_record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    if api_key_record.expires_at and api_key_record.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key expired",
        )

    user = db.query(User).filter(User.id == api_key_record.user_id).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    api_key_record.last_used_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(api_key_record)
    return ApiClientContext(user=user, api_key=api_key_record)
