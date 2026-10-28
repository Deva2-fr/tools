from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import admin_user, current_user, hash_password
from app.models import AuditLog, User
from app.routers.auth import audit
from app.schemas import UserCreate, UserOut

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    return db.scalars(select(User).order_by(User.email)).all()


@router.get("/directory")
def directory(_: User = Depends(current_user), db: Session = Depends(get_db)):
    """Liste minimale des utilisateurs actifs (nom, e-mail) pour les menus « Utilisateur »."""
    rows = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.name, User.email))
    return [{"id": u.id, "name": u.name or u.email, "email": u.email} for u in rows]


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    email = body.email.lower().strip()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Cet e-mail existe déjà")
    user = User(email=email, name=body.name, role=body.role, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    audit(db, admin.email, "user_created", email)
    return user


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404)
    if user.id == admin.id:
        raise HTTPException(400, "Vous ne pouvez pas supprimer votre propre compte")
    db.delete(user)
    db.commit()
    audit(db, admin.email, "user_deleted", user.email)


@router.get("/audit/log")
def audit_log(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(200)).all()
    return [{"ts": r.ts, "user": r.user_email, "action": r.action, "detail": r.detail} for r in rows]
