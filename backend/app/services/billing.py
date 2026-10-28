"""Devis & factures : totaux, numérotation continue, paiements, conversion, relances."""

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BillingDoc, BillingLine, Company, Counter, Payment
from app.schemas_billing import DocIn, LineIn
from app.services import integrations
from app.services.alerts import create_alert

PREFIX = {"quote": "DEV", "invoice": "FAC"}
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


def next_number(db: Session, kind: str, year: int) -> str:
    """Numéro séquentiel sans trou : attribué uniquement à l'émission, par type et par année."""
    key = f"{kind}-{year}"
    counter = db.scalar(select(Counter).where(Counter.key == key).with_for_update())
    if not counter:
        counter = Counter(key=key, value=0)
        db.add(counter)
    counter.value += 1
    db.flush()
    return f"{PREFIX[kind]}-{year}-{counter.value:04d}"


def set_lines(doc: BillingDoc, lines: list[LineIn]) -> None:
    doc.lines.clear()
    for i, ln in enumerate(lines):
        doc.lines.append(BillingLine(position=i, **ln.model_dump()))
    doc.total_ht, doc.total_vat, doc.total_ttc = compute_totals(doc.lines)


def is_editable(doc: BillingDoc) -> bool:
    # Une facture émise est immuable (obligation légale) : on l'annule et on en refait une.
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
        raise BillingError("Ce document est émis : il ne peut plus être modifié (annulez-le et recréez-le).")
    if data.kind != doc.kind:
        raise BillingError("Le type de document ne peut pas être changé.")
    for k, v in data.model_dump(exclude={"lines", "kind"}).items():
        setattr(doc, k, v)
    set_lines(doc, data.lines)
    db.commit()
    return doc


def issue(db: Session, doc: BillingDoc) -> BillingDoc:
    if doc.status != "draft":
        raise BillingError("Ce document est déjà émis.")
    if not doc.lines:
        raise BillingError("Ajoutez au moins une ligne avant d'émettre.")
    if doc.kind == "invoice" and not doc.company_id:
        raise BillingError("Une facture doit être rattachée à un client.")
    doc.number = next_number(db, doc.kind, doc.issue_date.year)
    doc.status = "sent"
    db.commit()
    return doc


def set_status(db: Session, doc: BillingDoc, status: str) -> BillingDoc:
    if doc.status == "draft":
        raise BillingError("Émettez d'abord le document.")
    allowed = {"quote": {"accepted", "refused", "sent"}, "invoice": {"cancelled"}}[doc.kind]
    if status not in allowed:
        raise BillingError("Changement de statut impossible pour ce type de document.")
    if doc.kind == "invoice" and doc.amount_paid > EPS:
        raise BillingError("Cette facture a des paiements : impossible de l'annuler.")
    doc.status = status
    db.commit()
    return doc


def convert_to_invoice(db: Session, quote: BillingDoc, user_email: str) -> BillingDoc:
    if quote.kind != "quote" or quote.status not in ("sent", "accepted"):
        raise BillingError("Seul un devis émis peut être transformé en facture.")
    existing = db.scalar(
        select(BillingDoc).where(BillingDoc.source_quote_id == quote.id, BillingDoc.status != "cancelled")
    )
    if existing:
        raise BillingError(f"Ce devis a déjà été facturé (facture n°{existing.number or existing.id}).")
    data = DocIn(
        kind="invoice",
        company_id=quote.company_id,
        contact_id=quote.contact_id,
        opportunity_id=quote.opportunity_id,
        title=quote.title,
        issue_date=date.today(),
        notes=quote.notes,
        lines=[
            LineIn(
                description=ln.description,
                quantity=ln.quantity,
                unit_price=ln.unit_price,
                vat_rate=ln.vat_rate,
            )
            for ln in quote.lines
        ],
    )
    inv = create_doc(db, data, user_email)
    inv.source_quote_id = quote.id
    quote.status = "accepted"
    db.commit()
    return inv


def refresh_payment_status(doc: BillingDoc) -> None:
    doc.amount_paid = round(sum(float(p.amount) for p in doc.payments), 2)
    if doc.status in ("sent", "paid"):
        doc.status = "paid" if doc.amount_paid >= doc.total_ttc - EPS and doc.total_ttc > 0 else "sent"


def add_payment(
    db: Session, doc: BillingDoc, paid_on: date, amount: float, method: str, note: str
) -> Payment:
    if doc.kind != "invoice" or doc.status not in ("sent", "paid"):
        raise BillingError("Les paiements s'enregistrent sur une facture émise.")
    if amount > doc.total_ttc - doc.amount_paid + EPS:
        raise BillingError("Le montant dépasse le reste à payer.")
    p = Payment(paid_on=paid_on, amount=amount, method=method, note=note)
    doc.payments.append(p)
    db.flush()
    refresh_payment_status(doc)
    db.commit()
    return p


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
