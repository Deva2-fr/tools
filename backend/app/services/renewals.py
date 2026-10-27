"""Abonnements, domaines, contrats : coût annuel, renouvellements et rappels."""

import calendar
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Subscription
from app.services.alerts import create_alert

PERIOD_MONTHS = {"monthly": 1, "quarterly": 3, "yearly": 12}
KIND_LABEL = {
    "domain": "Domaine",
    "hosting": "Hébergement",
    "saas": "Abonnement",
    "insurance": "Assurance",
    "contract": "Contrat",
    "other": "Renouvellement",
}


def add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def annual_cost(s: Subscription) -> float:
    return round(float(s.cost) * 12 / PERIOD_MONTHS[s.period], 2)


def occurrences(s: Subscription, start: date, end: date) -> list[date]:
    """Dates de prélèvement d'un abonnement entre `start` et `end` (inclus)."""
    if not s.renewal_date or not s.active:
        return []
    if not s.auto_renew:
        return [s.renewal_date] if start <= s.renewal_date <= end else []
    out, step, n = [], PERIOD_MONTHS[s.period], 0
    d = s.renewal_date
    while d <= end and n < 200:
        if d >= start:
            out.append(d)
        n += 1
        d = add_months(s.renewal_date, step * n)
    return out


def send_reminders(db: Session, today: date | None = None) -> int:
    today = today or date.today()
    sent = 0
    for s in db.scalars(
        select(Subscription).where(Subscription.active.is_(True), Subscription.renewal_date.is_not(None))
    ):
        left = (s.renewal_date - today).days
        thresholds = {s.notice_days, 7, 1, 0}
        if left < 0 or left not in thresholds:
            continue
        when = "AUJOURD'HUI" if left == 0 else f"dans {left} j"
        action = (
            "se renouvelle automatiquement"
            if s.auto_renew
            else "arrive à échéance (pas de renouvellement automatique)"
        )
        alert = create_alert(
            db,
            "renewal",
            "critical" if left <= 1 else "warning",
            f"{KIND_LABEL.get(s.kind, 'Renouvellement')} {when} : {s.name}",
            f"{s.name} {action} le {s.renewal_date:%d/%m/%Y} – {float(s.cost):.2f} € HT / {s.period}.",
            dedupe_key=f"sub:{s.id}:{s.renewal_date}:{left}",
            cooldown_hours=24 * 3650,
        )
        sent += 1 if alert else 0
    return sent


def roll_renewals(db: Session, today: date | None = None) -> int:
    """Fait avancer la date des abonnements à reconduction automatique déjà échus."""
    today = today or date.today()
    moved = 0
    for s in db.scalars(
        select(Subscription).where(
            Subscription.active.is_(True),
            Subscription.auto_renew.is_(True),
            Subscription.renewal_date < today,
        )
    ):
        while s.renewal_date < today:
            s.renewal_date = add_months(s.renewal_date, PERIOD_MONTHS[s.period])
        moved += 1
    db.commit()
    return moved
