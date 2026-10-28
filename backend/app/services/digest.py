"""Résumé quotidien : tout ce qui demande de l'attention aujourd'hui, en un seul message."""

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

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
)
from app.services import billing, outlook
from app.services.alerts import create_alert


def build(db: Session, today: date | None = None) -> list[str]:
    today = today or date.today()
    lines: list[str] = []

    down = db.scalars(select(Project).where(Project.status == "down")).all()
    if down:
        lines.append("🚨 Sites hors ligne : " + ", ".join(p.name for p in down))
    open_alerts = (
        db.scalar(
            select(func.count())
            .select_from(Alert)
            .where(Alert.acknowledged.is_(False), Alert.kind != "digest")
        )
        or 0
    )
    if open_alerts:
        lines.append(f"🔔 {open_alerts} alerte(s) non traitée(s)")

    mails = [
        m
        for m in db.scalars(select(MailMessage).order_by(MailMessage.received_at.desc()).limit(300))
        if outlook.display_tag(m) in ("a_repondre", "urgent")
    ]
    if mails:
        lines.append(f"✉️ {len(mails)} mail(s) à répondre")

    due = db.scalars(
        select(Task)
        .where(Task.done.is_(False), Task.due_date.is_not(None), Task.due_date <= today)
        .order_by(Task.due_date)
    ).all()
    if due:
        late = sum(t.due_date < today for t in due)
        lines.append(
            f"✅ {len(due)} tâche(s) à faire aujourd'hui ou en retard"
            + (f" (dont {late} en retard)" if late else "")
            + " : "
            + ", ".join(t.title for t in due[:4])
        )

    invoices = db.scalars(
        select(BillingDoc).where(BillingDoc.kind == "invoice", BillingDoc.status == "sent")
    ).all()
    late_inv = [d for d in invoices if billing.overdue(d, today)]
    if late_inv:
        lines.append(
            f"💶 {len(late_inv)} facture(s) en retard, {sum(billing.remaining(d) for d in late_inv):.2f} € à relancer"
        )

    taxes = db.scalars(
        select(TaxDeadline)
        .where(TaxDeadline.status == "todo", TaxDeadline.due_date <= today + timedelta(days=7))
        .order_by(TaxDeadline.due_date)
    ).all()
    if taxes:
        lines.append(
            "📅 Échéances fiscales sous 7 jours : "
            + ", ".join(f"{t.title} ({t.due_date:%d/%m})" for t in taxes[:4])
        )

    subs = db.scalars(
        select(Subscription).where(
            Subscription.active.is_(True),
            Subscription.renewal_date.is_not(None),
            Subscription.renewal_date <= today + timedelta(days=14),
        )
    ).all()
    if subs:
        lines.append(
            "🔄 Renouvellements sous 14 jours : "
            + ", ".join(f"{s.name} ({s.renewal_date:%d/%m})" for s in subs[:4])
        )

    soon = db.scalars(
        select(Opportunity).where(
            Opportunity.stage.in_(("quote", "negotiation")),
            Opportunity.expected_close.is_not(None),
            Opportunity.expected_close <= today + timedelta(days=7),
        )
    ).all()
    if soon:
        lines.append("🤝 Opportunités à conclure sous 7 jours : " + ", ".join(o.title for o in soon[:4]))

    pending = (
        db.scalar(select(func.count()).select_from(LeaveRequest).where(LeaveRequest.status == "pending")) or 0
    )
    if pending:
        lines.append(f"🏖️ {pending} demande(s) de congés à valider")
    return lines


def send(db: Session, today: date | None = None) -> bool:
    today = today or date.today()
    lines = build(db, today)
    if not lines:
        return False
    alert = create_alert(
        db,
        "digest",
        "info",
        f"Résumé du {today:%d/%m/%Y}",
        "\n".join(lines),
        dedupe_key=f"digest:{today}",
        cooldown_hours=20,
    )
    return alert is not None
