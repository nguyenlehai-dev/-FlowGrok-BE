import os
import hashlib
import hmac
import bcrypt
import threading
import time
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt

# Secret key dùng để sign JWT - trong production nên đặt vào biến môi trường
SECRET_KEY = os.getenv("SECRET_KEY", "flowgrok-super-secret-key-change-me-in-production")
WORKER_TOKEN = os.getenv("WORKER_TOKEN", "")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24
_RATE_LIMIT_LOCK = threading.Lock()
_RATE_LIMIT_STATE: dict[str, tuple[float, int]] = {}


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """So khớp password thô với hash đã lưu trong DB."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def get_password_hash(password: str) -> str:
    """Băm password trước khi lưu vào DB."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_access_token(data: dict) -> str:
    """Tạo JWT access token, sống 24 tiếng."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> dict | None:
    """Giải mã JWT token. Trả về None nếu token không hợp lệ hoặc hết hạn."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def verify_api_key(raw_key: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    return hmac.compare_digest(hash_api_key(raw_key), stored_hash)


def verify_worker_token(raw_token: str | None) -> bool:
    if not WORKER_TOKEN or not raw_token:
        return False
    return hmac.compare_digest(raw_token, WORKER_TOKEN)


def get_cors_origins() -> list[str]:
    raw_origins = os.getenv("CORS_ORIGINS", "")
    if not raw_origins.strip():
        return [
            "http://localhost:3000",
            "http://localhost:5173",
            "https://testflowgrok.plxeditor.com",
            "https://flowgrok.plxeditor.com",
        ]
    return [origin.strip() for origin in raw_origins.split(",") if origin.strip()]


def check_rate_limit(key: str, limit_per_minute: int, window_seconds: int = 60) -> bool:
    if limit_per_minute <= 0:
        return True

    now = time.time()
    window_start = now - window_seconds
    with _RATE_LIMIT_LOCK:
        bucket = _RATE_LIMIT_STATE.get(key)
        if not bucket or bucket[0] < window_start:
            _RATE_LIMIT_STATE[key] = (now, 1)
            return True

        started_at, count = bucket
        if count >= limit_per_minute:
            return False

        _RATE_LIMIT_STATE[key] = (started_at, count + 1)
        return True
