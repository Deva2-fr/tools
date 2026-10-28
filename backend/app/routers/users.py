from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import admin_user, current_user, hash_password, is_manager
from app.models import AuditLog, Expense, Opportunity, Signature, Subscription, Task, TimeEntry, User
from app.routers.auth import audit
from app.routers.expenses import signer_ids
from app.schemas import UserCreate, UserOut
from app.services import renewals

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    return db.scalars(select(User).order_by(User.email)).all()


@router.get("/directory")
def directory(_: User = Depends(current_user), db: Session = Depends(get_db)):
    """Liste minimale des utilisateurs actifs (nom, e-mail) pour les menus « Utilisateur »."""
    rows = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.name, User.email))
    return [{"id": u.id, "name": u.name or u.email, "email": u.email} for u in rows]


@router.get("/{user_id}/summary")
def summary(user_id: int, me: User = Depends(current_user), db: Session = Depends(get_db)):
    """Profil : tout ce qui est rattaché à un utilisateur. Visible par lui-même et par les managers."""
    if me.id != user_id and not is_manager(me):
        raise HTTPException(403, "Profil réservé à son titulaire et aux managers")
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404)

    today = date.today()
    expenses = db.scalars(
        select(Expense)
        .where(Expense.user_id == u.id)
        .order_by(Expense.expense_date.desc(), Expense.id.desc())
    ).all()
    year = [e for e in expenses if e.expense_date.year == today.year]
    subs = db.scalars(
        select(Subscription).where(Subscription.user_id == u.id).order_by(Subscription.name)
    ).all()
    active = [x for x in subs if x.active]
    tasks = db.scalars(select(Task).where(Task.assignee_email == u.email, Task.done.is_(False))).all()
    opps = db.scalars(
        select(Opportunity).where(
            Opportunity.owner_email == u.email, Opportunity.stage.not_in(("won", "lost"))
        )
    ).all()
    month_hours = sum(
        float(t.hours)
        for t in db.scalars(
            select(TimeEntry).where(
                TimeEntry.user_email == u.email, TimeEntry.work_date >= today.replace(day=1)
            )
        )
    )
    roles = [r for r, uid in signer_ids(db).items() if uid == u.id]
    return {
        "user": {
            "id": u.id,
            "name": u.name or u.email,
            "email": u.email,
            "role": u.role,
            "is_active": u.is_active,
            "totp_enabled": u.totp_enabled,
            "created_at": u.created_at,
            "signer_roles": roles,  # president / partner
        },
        "expenses": {
            "count": len(expenses),
            "year_count": len(year),
            "year_total": round(sum(e.amount_ttc for e in year), 2),
            "total": round(sum(e.amount_ttc for e in expenses), 2),
            "without_receipt": sum(1 for e in expenses if not e.receipts),
            "recent": [
                {
                    "id": e.id,
                    "date": e.expense_date,
                    "reason": e.reason,
                    "amount": e.amount_ttc,
                    "receipts": len(e.receipts),
                }
                for e in expenses[:8]
            ],
        },
        "subscriptions": {
            "count": len(subs),
            "active": len(active),
            "annual_cost": round(sum(renewals.annual_cost(x) for x in active), 2),
            "items": [
                {
                    "id": x.id,
                    "name": x.name,
                    "vendor": x.vendor,
                    "annual_cost": renewals.annual_cost(x),
                    "renewal_date": x.renewal_date,
                    "active": x.active,
                }
                for x in subs
            ],
        },
        "signatures": len(db.scalars(select(Signature.id).where(Signature.user_id == u.id)).all()),
        "tasks": {
            "open": len(tasks),
            "overdue": sum(1 for t in tasks if t.due_date and t.due_date < today),
        },
        "opportunities": {"open": len(opps), "amount": round(sum(o.amount for o in opps), 2)},
        "time": {"month_hours": round(month_hours, 2)},
    }


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
