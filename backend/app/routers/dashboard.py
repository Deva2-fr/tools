from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import current_user
from app.models import Alert, MailMessage, Project, TaxDeadline, Vulnerability
from app.services import outlook

router = APIRouter(tags=["tableau de bord"], dependencies=[Depends(current_user)])


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
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
    return {
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
    }
