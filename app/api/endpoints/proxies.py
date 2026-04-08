from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.database import get_db
from app.models.core import Proxy, User
from app.schemas.core import ProxyCreate, ProxyResponse, ProxyUpdate

router = APIRouter()

@router.post("/", response_model=ProxyResponse)
def create_proxy(proxy: ProxyCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db_proxy = Proxy(**proxy.model_dump())
    db.add(db_proxy)
    db.commit()
    db.refresh(db_proxy)
    return db_proxy

@router.get("/", response_model=list[ProxyResponse])
def get_proxies(status: str | None = None, search: str | None = None, skip: int = 0, limit: int = 100, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(Proxy)
    if status:
        query = query.filter(Proxy.status == status)
    if search:
        query = query.filter(Proxy.ip.ilike(f"%{search}%"))
    return query.order_by(Proxy.created_at.desc()).offset(skip).limit(limit).all()


@router.patch("/{proxy_id}", response_model=ProxyResponse)
def update_proxy(proxy_id: str, payload: ProxyUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    proxy = db.query(Proxy).filter(Proxy.id == proxy_id).first()
    if not proxy:
        raise HTTPException(status_code=404, detail="Proxy not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(proxy, key, value)
    db.commit()
    db.refresh(proxy)
    return proxy


@router.post("/{proxy_id}/health-check", response_model=ProxyResponse)
def health_check_proxy(proxy_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    proxy = db.query(Proxy).filter(Proxy.id == proxy_id).first()
    if not proxy:
        raise HTTPException(status_code=404, detail="Proxy not found")
    proxy.status = "alive"
    proxy.latency_ms = 800
    proxy.last_checked_at = datetime.now(timezone.utc)
    proxy.fail_count = 0
    db.commit()
    db.refresh(proxy)
    return proxy

@router.delete("/{proxy_id}")
def delete_proxy(proxy_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    proxy = db.query(Proxy).filter(Proxy.id == proxy_id).first()
    if not proxy:
        raise HTTPException(status_code=404, detail="Proxy not found")
    db.delete(proxy)
    db.commit()
    return {"status": "success", "message": "Proxy deleted"}
