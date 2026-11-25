import calendar
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TaxDeadline
from app.services import integrations
from app.services.alerts import create_alert

# Échéances types de Deva2 (société à l'IS, exercice = année civile) : TVA trimestrielle, liasse
# fiscale et comptes sociaux, AG d'approbation des comptes, dépôt au greffe et CFE. Pas d'URSSAF ni
# d'acomptes d'IS. Dates limites légales : à valider avec votre comptable.
# `months` : mois d'échéance ; `{trimestre}` = trimestre déclaré ; `{exercice}` = exercice clos (N-1).
QUARTER_DECLARED = {1: "T4", 4: "T1", 7: "T2", 10: "T3"}
TEMPLATES = [
    {
        "title": "TVA trimestrielle – déclaration CA3 ({trimestre})",
        "category": "tva",
        "months": [1, 4, 7, 10],
        "day": 20,
        "notes": "TVA du trimestre écoulé. Date limite entre le 15 et le 24 selon votre SIE "
        "(impots.gouv > Professionnel > Mes échéances).",
    },
    {
        "title": "Comptes sociaux et liasse fiscale – impots.gouv (exercice {exercice})",
        # Ancien titre : une échéance déjà créée sous ce nom n'est pas recréée.
        "old_title": "Déclaration annuelle de résultats (liasse fiscale)",
        "category": "is",
        "months": [5],
        "day": 15,
        "notes": "Exercice clos au 31/12 : comptes sociaux (bilan, compte de résultat, annexes) transmis "
        "avec la liasse 2065 sur impots.gouv. Pas d'acompte d'IS : l'éventuel IS est réglé en une fois "
        "avec le relevé de solde 2572, à la même date.",
    },
    {
        "title": "Assemblée générale ordinaire – approbation des comptes (exercice {exercice})",
        "category": "comptes",
        "months": [6],
        "day": 30,
        "reminder_days": "60,30,15,7",
        "notes": "Dans les 6 mois suivant la clôture. Convoquer les associés selon les statuts (souvent "
        "15 jours avant), préparer le rapport de gestion, puis rédiger et signer le PV d'approbation des "
        "comptes et d'affectation du résultat.",
    },
    {
        "title": "Dépôt des comptes sociaux au greffe (exercice {exercice})",
        "category": "comptes",
        "months": [7],
        "day": 31,
        "reminder_days": "30,15,7,1",
        "notes": "Dans le mois qui suit l'AGO (deux mois si dépôt en ligne sur le guichet unique / "
        "infogreffe) : comptes annuels, PV d'approbation et d'affectation du résultat. Une petite "
        "entreprise peut joindre une déclaration de confidentialité des comptes.",
    },
    {
        "title": "CFE – avis à payer",
        "category": "cfe",
        "months": [12],
        "day": 15,
        "notes": "Avis disponible en novembre dans votre espace professionnel impots.gouv.",
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


def generate_year(db: Session, year: int, not_before: date | None = None) -> int:
    """Crée les échéances modèles d'une année (sans doublon). `not_before` : ignore les dates passées."""
    created = 0
    for t in TEMPLATES:
        for m in t["months"]:
            due = _clamp(year, m, t["day"])
            if not_before and due < not_before:
                continue
            title = t["title"].format(
                trimestre=f"{QUARTER_DECLARED.get(m, '')} {year - 1 if m == 1 else year}", exercice=year - 1
            )
            titles = [title] + ([t["old_title"]] if t.get("old_title") else [])
            exists = db.scalar(
                select(TaxDeadline.id).where(TaxDeadline.title.in_(titles), TaxDeadline.due_date == due)
            )
            if not exists:
                # Chaque occurrence est créée explicitement : pas de récurrence à régénérer.
                db.add(
                    TaxDeadline(
                        title=title,
                        category=t["category"],
                        due_date=due,
                        notes=t["notes"],
                        recurrence="none",
                        reminder_days=t.get("reminder_days", "30,7,1"),
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


def auto_generate(db: Session, today: date | None = None) -> int:
    """Échéances à venir de l'année en cours, et dès décembre celles de l'année suivante.
    Une seule fois par année : une échéance supprimée volontairement n'est pas recréée."""
    today = today or date.today()
    created = 0
    for year, not_before in ((today.year, today), (today.year + 1, None)):
        if year > today.year and today.month != 12:
            continue
        key = f"taxes_auto_generated_{year}"
        if integrations.get(db, key):
            continue
        created += generate_year(db, year, not_before=not_before)
        integrations.put(db, key, today.isoformat())
    return created


def _next_occurrence(db: Session, deadline: TaxDeadline) -> TaxDeadline | None:
    """Occurrence suivante créée automatiquement par « c'est payé », si personne n'y a touché."""
    due = next_due(deadline.due_date, deadline.recurrence)
    if due is None:
        return None
    return db.scalar(
        select(TaxDeadline).where(
            TaxDeadline.title == deadline.title,
            TaxDeadline.due_date == due,
            TaxDeadline.recurrence == deadline.recurrence,
            TaxDeadline.status == "todo",
            TaxDeadline.amount.is_(None),
        )
    )


def mark_unpaid(db: Session, deadline: TaxDeadline) -> int | None:
    """Annule un « c'est payé » : l'échéance repasse à faire et l'occurrence suivante créée
    automatiquement est supprimée. Renvoie l'id supprimé (pour Google Agenda), sinon None."""
    if deadline.status != "paid":
        return None
    deadline.status = "todo"
    removed = None
    if deadline.recurrence != "none" and (nxt := _next_occurrence(db, deadline)):
        removed = nxt.id
        db.delete(nxt)
    db.commit()
    return removed


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
