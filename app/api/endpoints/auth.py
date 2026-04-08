import secrets
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.db.database import get_db
from app.core.security import verify_password, get_password_hash, create_access_token
from app.core.deps import get_current_user
from app.models.core import User, ApiKey

router = APIRouter()


# === Schemas ===
class RegisterRequest(BaseModel):
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserResponse(BaseModel):
    id: str
    email: str
    role: str
    is_active: bool
    class Config:
        from_attributes = True

class ApiKeyResponse(BaseModel):
    id: str
    key: str
    status: str
    name: str | None = None
    key_preview: str | None = None
    rate_limit_per_minute: int | None = None
    last_used_at: datetime | None = None
    class Config:
        from_attributes = True


# === Auth Endpoints ===

@router.post("/register", response_model=UserResponse)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """Đăng ký tài khoản mới."""
    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=req.email,
        hashed_password=get_password_hash(req.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    """Đăng nhập và nhận JWT access token (sống 24h)."""
    user = db.query(User).filter(User.email == req.email).first()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    token = create_access_token(data={"sub": user.id})
    return {"access_token": token}


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """Lấy thông tin user đang đăng nhập."""
    return current_user


# === API Key Management ===

@router.post("/api-keys", response_model=ApiKeyResponse)
def create_api_key(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Sinh một API Key mới cho user hiện tại."""
    key = f"fgk_{secrets.token_urlsafe(32)}"
    api_key = ApiKey(user_id=current_user.id, key=key, key_preview=f"{key[:10]}...{key[-6:]}")
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return api_key


@router.get("/api-keys", response_model=list[ApiKeyResponse])
def list_api_keys(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Liệt kê tất cả API Keys của user hiện tại."""
    keys = db.query(ApiKey).filter(ApiKey.user_id == current_user.id).all()
    return keys


@router.delete("/api-keys/{key_id}")
def revoke_api_key(key_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Thu hồi (vô hiệu hóa) một API Key."""
    api_key = db.query(ApiKey).filter(ApiKey.id == key_id, ApiKey.user_id == current_user.id).first()
    if not api_key:
        raise HTTPException(status_code=404, detail="API Key not found")
    api_key.status = "revoked"
    db.commit()
    return {"status": "success", "message": "API Key revoked"}
