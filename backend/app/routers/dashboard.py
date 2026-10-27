from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import current_user
from app.models import (
    Alert,
    BillingDoc,
    LeaveRequest,
    MailMessage,
    Opportunity,
    Project,
    Subscription,
    Task,
    TaxDeadline,
    User,
    Vulnerability,
)
from app.services import billing, outlook, treasury

router = APIRouter(tags=["tableau de bord"])


@router.get("/dashboard")
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    projects = db.scalars(select(Project)).all()
    today = date.today()
    taxes = db.scalars(
        select(TaxDeadline)
        .where(TaxDeadline.status == "todo", TaxDeadline.due_date <= today + timedelta(days=45))
        .order_by(TaxDeadline.due_date)
    ).all()
    mails = db.scalars(select(MailMessage).order_by(MailMessage.received_at.desc()).limit(300)).all()
    to_reply = [m for m in mails if outlook.display_tag(m) in ("a_repondre", "urgent")]
    open_alerts = db.scalars(
        select(Alert).where(Alert.acknowledged.is_(False)).order_by(Alert.id.desc()).limit(8)
    ).all()

    my_tasks = db.scalars(
        select(Task)
        .where(Task.done.is_(False), (Task.assignee_email == user.email) | (Task.assignee_email == ""))
        .order_by(Task.due_date.is_(None), Task.due_date)
        .limit(8)
    ).all()
    open_opps = db.scalars(
        select(Opportunity).where(Opportunity.stage.in_(("prospect", "contact", "quote", "negotiation")))
    ).all()
    data = {
        "projects": {
            "total": len(projects),
            "up": sum(p.status == "up" for p in projects),
            "down": sum(p.status == "down" for p in projects),
            "items": [
                {
                    "id": p.id,
                    "name": p.name,
                    "url": p.url,
                    "status": p.status,
                    "latency_ms": p.last_latency_ms,
                }
                for p in projects
            ],
        },
        "alerts_open": db.scalar(select(func.count()).select_from(Alert).where(Alert.acknowledged.is_(False)))
        or 0,
        "alerts": [
            {"id": a.id, "title": a.title, "severity": a.severity, "created_at": a.created_at}
            for a in open_alerts
        ],
        "vulnerabilities_open": db.scalar(
            select(func.count()).select_from(Vulnerability).where(Vulnerability.dismissed.is_(False))
        )
        or 0,
        "mails_to_reply": len(to_reply),
        "taxes_upcoming": [
            {
                "id": t.id,
                "title": t.title,
                "due_date": t.due_date,
                "days_left": (t.due_date - today).days,
                "amount": t.amount,
            }
            for t in taxes[:6]
        ],
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "due_date": t.due_date,
                "late": bool(t.due_date and t.due_date < today),
            }
            for t in my_tasks
        ],
        "pipeline": {
            "open_count": len(open_opps),
            "forecast": round(sum(o.amount * o.probability / 100 for o in open_opps), 2),
        },
        "finance": None,
    }
    if user.role in ("admin", "manager"):
        invoices = db.scalars(
            select(BillingDoc).where(BillingDoc.kind == "invoice", BillingDoc.status.in_(("sent", "paid")))
        ).all()
        year = [d for d in invoices if d.issue_date.year == today.year]
        renewals_soon = db.scalars(
            select(Subscription)
            .where(
                Subscription.active.is_(True),
                Subscription.renewal_date.is_not(None),
                Subscription.renewal_date <= today + timedelta(days=30),
            )
            .order_by(Subscription.renewal_date)
        ).all()
        data["finance"] = {
            "invoiced_ht": round(sum(d.total_ht for d in year), 2),
            "outstanding": round(sum(billing.remaining(d) for d in invoices), 2),
            "overdue": round(sum(billing.remaining(d) for d in invoices if billing.overdue(d)), 2),
            "balance": treasury.current_balance(db),
            "renewals": [
                {"id": s.id, "name": s.name, "date": s.renewal_date, "cost": s.cost}
                for s in renewals_soon[:5]
            ],
            "leaves_pending": db.scalar(
                select(func.count()).select_from(LeaveRequest).where(LeaveRequest.status == "pending")
            )
            or 0,
        }
    return data
