import calendar
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TaxDeadline
from app.services.alerts import create_alert

# Modèles indicatifs pour une société française à l'IS (exercice = année civile).
# Les dates varient selon votre régime et votre date de clôture : à valider avec votre comptable.
TEMPLATES = [
    {
        "title": "TVA – déclaration CA3 mensuelle",
        "category": "tva",
        "month": None,
        "day": 20,
        "recurrence": "monthly",
        "notes": "Date limite entre le 15 et le 24 selon votre SIE (impots.gouv > Professionnel).",
    },
    {
        "title": "Acompte d'IS n°1",
        "category": "is",
        "month": 3,
        "day": 15,
        "recurrence": "yearly",
        "notes": "",
    },
    {
        "title": "Solde de l'IS",
        "category": "is",
        "month": 5,
        "day": 15,
        "recurrence": "yearly",
        "notes": "Exercice clos au 31/12.",
    },
    {
        "title": "Acompte d'IS n°2",
        "category": "is",
        "month": 6,
        "day": 15,
        "recurrence": "yearly",
        "notes": "",
    },
    {
        "title": "Acompte de CFE",
        "category": "cfe",
        "month": 6,
        "day": 15,
        "recurrence": "yearly",
        "notes": "Si CFE > 3 000 €.",
    },
    {
        "title": "Acompte d'IS n°3",
        "category": "is",
        "month": 9,
        "day": 15,
        "recurrence": "yearly",
        "notes": "",
    },
    {
        "title": "Acompte d'IS n°4",
        "category": "is",
        "month": 12,
        "day": 15,
        "recurrence": "yearly",
        "notes": "",
    },
    {"title": "Solde de CFE", "category": "cfe", "month": 12, "day": 15, "recurrence": "yearly", "notes": ""},
    {
        "title": "Dépôt des comptes annuels (greffe)",
        "category": "comptes",
        "month": 7,
        "day": 31,
        "recurrence": "yearly",
        "notes": "Dans le mois suivant l'approbation des comptes (AG sous 6 mois après clôture).",
    },
    {
        "title": "DAS2 (honoraires versés)",
        "category": "social",
        "month": 2,
        "day": 1,
        "recurrence": "yearly",
        "notes": "",
    },
    {
        "title": "TVA – régularisation annuelle (CA12)",
        "category": "tva",
        "month": 5,
        "day": 2,
        "recurrence": "yearly",
        "notes": "Uniquement si vous êtes au régime simplifié.",
    },
    {
        "title": "URSSAF – cotisations mensuelles",
        "category": "urssaf",
        "month": None,
        "day": 15,
        "recurrence": "monthly",
        "notes": "Le 5 ou le 15 selon votre périodicité.",
    },
]


def _clamp(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def next_due(due: date, recurrence: str) -> date | None:
    if recurrence == "monthly":
        y, m = (due.year + 1, 1) if due.month == 12 else (due.year, due.month + 1)
        return _clamp(y, m, due.day)
    if recurrence == "quarterly":
        m = due.month + 3
        y = due.year + (m - 1) // 12
        return _clamp(y, (m - 1) % 12 + 1, due.day)
    if recurrence == "yearly":
        return _clamp(due.year + 1, due.month, due.day)
    return None


def generate_year(db: Session, year: int) -> int:
    """Crée les échéances modèles d'une année (sans doublon)."""
    created = 0
    for t in TEMPLATES:
        months = range(1, 13) if t["month"] is None else [t["month"]]
        for m in months:
            due = _clamp(year, m, t["day"])
            exists = db.scalar(
                select(TaxDeadline.id).where(TaxDeadline.title == t["title"], TaxDeadline.due_date == due)
            )
            if not exists:
                # Chaque occurrence est créée explicitement : pas de récurrence à régénérer.
                db.add(
                    TaxDeadline(
                        title=t["title"],
                        category=t["category"],
                        due_date=due,
                        notes=t["notes"],
                        recurrence="none",
                    )
                )
                created += 1
    db.commit()
    return created


def mark_paid(db: Session, deadline: TaxDeadline) -> TaxDeadline | None:
    deadline.status = "paid"
    nxt = None
    if deadline.recurrence != "none":
        due = next_due(deadline.due_date, deadline.recurrence)
        nxt = TaxDeadline(
            title=deadline.title,
            category=deadline.category,
            due_date=due,
            amount=None,
            recurrence=deadline.recurrence,
            reminder_days=deadline.reminder_days,
            notes=deadline.notes,
        )
        db.add(nxt)
    db.commit()
    return nxt


def send_reminders(db: Session, today: date | None = None) -> int:
    today = today or date.today()
    sent = 0
    for d in db.scalars(
        select(TaxDeadline).where(
            TaxDeadline.status == "todo", TaxDeadline.due_date <= today + timedelta(days=60)
        )
    ):
        left = (d.due_date - today).days
        days = {int(x) for x in d.reminder_days.split(",") if x.strip().isdigit()}
        amount = f" – {d.amount:.2f} €" if d.amount else ""
        if left < 0:
            alert = create_alert(
                db,
                "tax",
                "critical",
                f"EN RETARD ({-left} j) : {d.title}",
                f"Échéance du {d.due_date:%d/%m/%Y}{amount}",
                dedupe_key=f"tax:{d.id}:late:{today}",
                cooldown_hours=20,
            )
        elif left in days or left == 0:
            sev = "critical" if left <= 1 else "warning"
            when = "AUJOURD'HUI" if left == 0 else f"dans {left} j"
            alert = create_alert(
                db,
                "tax",
                sev,
                f"Échéance {when} : {d.title}",
                f"À régler le {d.due_date:%d/%m/%Y}{amount}",
                dedupe_key=f"tax:{d.id}:{left}",
                cooldown_hours=20,
            )
        else:
            continue
        sent += 1 if alert else 0
    return sent


def to_ics(deadlines: list[TaxDeadline]) -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Deva2 Hub//Echeances//FR", "CALSCALE:GREGORIAN"]
    for d in deadlines:
        lines += [
            "BEGIN:VEVENT",
            f"UID:tax-{d.id}@deva2-hub",
            f"DTSTAMP:{d.created_at:%Y%m%dT%H%M%SZ}",
            f"DTSTART;VALUE=DATE:{d.due_date:%Y%m%d}",
            f"SUMMARY:{'✔ ' if d.status == 'paid' else ''}{d.title}".replace(",", "\\,"),
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            "DESCRIPTION:Echeance",
            "TRIGGER:-P7D",
            "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
