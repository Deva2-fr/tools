"""Devis & factures du Hub : brouillons (totaux, lignes), retards et alertes d'impayés des factures."""

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BillingDoc, BillingLine, Company
from app.schemas_billing import DocIn, LineIn
from app.services import integrations
from app.services.alerts import create_alert

EPS = 0.005


class BillingError(ValueError):
    """Règle métier violée (message affichable à l'utilisateur)."""


def compute_totals(lines: list) -> tuple[float, float, float]:
    """TVA calculée par taux sur le total HT du taux (règle française), arrondie au centime."""
    by_rate: dict[float, float] = defaultdict(float)
    for ln in lines:
        by_rate[float(ln.vat_rate)] += round(float(ln.quantity) * float(ln.unit_price), 2)
    ht = round(sum(by_rate.values()), 2)
    vat = round(sum(round(base * rate / 100, 2) for rate, base in by_rate.items()), 2)
    return ht, vat, round(ht + vat, 2)


def vat_breakdown(lines: list) -> list[tuple[float, float, float]]:
    by_rate: dict[float, float] = defaultdict(float)
    for ln in lines:
        by_rate[float(ln.vat_rate)] += round(float(ln.quantity) * float(ln.unit_price), 2)
    return [(rate, base, round(base * rate / 100, 2)) for rate, base in sorted(by_rate.items())]


def set_lines(doc: BillingDoc, lines: list[LineIn]) -> None:
    doc.lines.clear()
    for i, ln in enumerate(lines):
        doc.lines.append(BillingLine(position=i, **ln.model_dump()))
    doc.total_ht, doc.total_vat, doc.total_ttc = compute_totals(doc.lines)


def is_editable(doc: BillingDoc) -> bool:
    # Le Hub ne prépare que des brouillons ; un document déjà émis (avant cette règle) reste consultable.
    return doc.status == "draft" or (doc.kind == "quote" and doc.status == "sent")


def create_doc(db: Session, data: DocIn, user_email: str) -> BillingDoc:
    doc = BillingDoc(**data.model_dump(exclude={"lines"}), created_by=user_email)
    if doc.kind == "invoice" and not doc.due_date:
        doc.due_date = doc.issue_date + timedelta(days=integrations.terms_days(db))
    if doc.kind == "quote" and not doc.due_date:
        doc.due_date = doc.issue_date + timedelta(days=30)
    set_lines(doc, data.lines)
    db.add(doc)
    db.commit()
    return doc


def update_doc(db: Session, doc: BillingDoc, data: DocIn) -> BillingDoc:
    if not is_editable(doc):
        raise BillingError("Ce document a déjà été émis : il ne peut plus être modifié ici.")
    if data.kind != doc.kind:
        raise BillingError("Le type de document ne peut pas être changé.")
    for k, v in data.model_dump(exclude={"lines", "kind"}).items():
        setattr(doc, k, v)
    set_lines(doc, data.lines)
    db.commit()
    return doc


def remaining(doc: BillingDoc) -> float:
    if doc.kind != "invoice" or doc.status in ("draft", "cancelled"):
        return 0.0
    return round(max(doc.total_ttc - doc.amount_paid, 0), 2)


def overdue(doc: BillingDoc, today: date | None = None) -> bool:
    today = today or date.today()
    return doc.kind == "invoice" and doc.status == "sent" and bool(doc.due_date) and doc.due_date < today


REMINDER_STEPS = (1, 7, 15, 30)


def send_reminders(db: Session, today: date | None = None) -> int:
    """Alerte sur les factures arrivant à échéance ou en retard (J-3, puis J+1, J+7, J+15, J+30 et tous les 30 j)."""
    today = today or date.today()
    sent = 0
    docs = db.scalars(
        select(BillingDoc).where(BillingDoc.kind == "invoice", BillingDoc.status == "sent")
    ).all()
    for d in docs:
        if not d.due_date:
            continue
        client = db.get(Company, d.company_id).name if d.company_id else "client inconnu"
        late = (today - d.due_date).days
        left = round(remaining(d), 2)
        if late > 0:
            step = max((s for s in REMINDER_STEPS if late >= s), default=0)
            if late > 30:
                step = 30 * (late // 30)
            alert = create_alert(
                db,
                "invoice",
                "critical" if late >= 15 else "warning",
                f"Facture {d.number} impayée depuis {late} j – {client}",
                f"Reste à encaisser : {left:.2f} € (échéance {d.due_date:%d/%m/%Y}). Pensez à relancer le client.",
                dedupe_key=f"inv:{d.id}:late:{step}",
                cooldown_hours=24 * 3650,
            )
        elif (d.due_date - today).days == 3:
            alert = create_alert(
                db,
                "invoice",
                "info",
                f"Facture {d.number} à échéance dans 3 jours – {client}",
                f"{left:.2f} € attendus le {d.due_date:%d/%m/%Y}.",
                dedupe_key=f"inv:{d.id}:soon",
                cooldown_hours=24 * 3650,
            )
        else:
            continue
        sent += 1 if alert else 0
    return sent
