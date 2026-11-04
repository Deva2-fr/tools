from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import admin_user, current_user, hash_password, is_manager
from app.models import AuditLog, Expense, Opportunity, Signature, Subscription, Task, TimeEntry, User
from app.routers.auth import audit
from app.routers.expenses import signer_ids
from app.schemas import PasswordReset, UserCreate, UserOut, UserUpdate
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


def _get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404)
    return user


def _other_active_admins(db: Session, user: User) -> int:
    return len(
        db.scalars(
            select(User.id).where(User.role == "admin", User.is_active.is_(True), User.id != user.id)
        ).all()
    )


def _new_session(user: User) -> None:
    """Ferme toutes les sessions ouvertes de cet utilisateur."""
    user.session_version = (user.session_version or 0) + 1


@router.put("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int, body: UserUpdate, admin: User = Depends(admin_user), db: Session = Depends(get_db)
):
    user = _get_user(db, user_id)
    email = body.email.lower().strip()
    losing_admin = user.role == "admin" and user.is_active and (body.role != "admin" or not body.is_active)
    if user.id == admin.id and losing_admin:
        raise HTTPException(
            400, "Vous ne pouvez pas retirer vos propres droits d'administrateur ni vous désactiver"
        )
    if losing_admin and not _other_active_admins(db, user):
        raise HTTPException(400, "Il faut garder au moins un administrateur actif")
    if email != user.email and db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Cet e-mail est déjà utilisé")
    changes = [
        label
        for label, old, new in (
            ("nom", user.name, body.name.strip()),
            ("e-mail", user.email, email),
            ("rôle", user.role, body.role),
        )
        if old != new
    ]
    if email != user.email or (user.is_active and not body.is_active):
        _new_session(user)
    if user.is_active != body.is_active:
        changes.append("réactivé" if body.is_active else "désactivé")
    old_email = user.email
    user.name, user.email, user.role, user.is_active = body.name.strip(), email, body.role, body.is_active
    db.commit()
    if changes:
        audit(db, admin.email, "user_updated", f"{old_email} : {', '.join(changes)}")
    return user


@router.post("/{user_id}/password", status_code=204)
def reset_password(
    user_id: int, body: PasswordReset, admin: User = Depends(admin_user), db: Session = Depends(get_db)
):
    """Mot de passe provisoire choisi par l'admin (oubli) : les sessions de la personne sont fermées."""
    user = _get_user(db, user_id)
    user.password_hash = hash_password(body.new_password)
    _new_session(user)
    db.commit()
    audit(db, admin.email, "user_password_reset", user.email)


@router.post("/{user_id}/reset-2fa", status_code=204)
def reset_2fa(user_id: int, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Téléphone perdu : la 2FA est retirée, la personne la réactivera elle-même."""
    user = _get_user(db, user_id)
    user.totp_enabled, user.totp_secret_enc = False, None
    db.commit()
    audit(db, admin.email, "user_2fa_reset", user.email)


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    user = _get_user(db, user_id)
    if user.id == admin.id:
        raise HTTPException(400, "Vous ne pouvez pas supprimer votre propre compte")
    if user.role == "admin" and user.is_active and not _other_active_admins(db, user):
        raise HTTPException(400, "Il faut garder au moins un administrateur actif")
    db.delete(user)
    db.commit()
    audit(db, admin.email, "user_deleted", user.email)


@router.get("/audit/log")
def audit_log(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(200)).all()
    return [{"ts": r.ts, "user": r.user_email, "action": r.action, "detail": r.detail} for r in rows]
