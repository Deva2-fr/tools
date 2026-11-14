"""Renouvellement des contrats clients : le Hub prépare le devis en brouillon avant l'échéance.

Un brouillon par client regroupe les contrats arrivant à échéance (hébergement, domaine,
maintenance…). La validation et l'envoi au client se font dans Qonto, comme tout devis.
"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BillingDoc, ClientContract, Company
from app.schemas_billing import DocIn, LineIn
from app.services import billing, qonto_billing
from app.services.alerts import create_alert
from app.services.renewals import PERIOD_MONTHS, add_months

KINDS = {
    "hosting": "Hébergement",
    "domain": "Nom de domaine",
    "maintenance": "Maintenance / TMA",
    "license": "Licence / logiciel",
    "other": "Autre",
}
URGENT_DAYS = 7


def period_end(start: date, period: str) -> date:
    return add_months(start, PERIOD_MONTHS[period]) - timedelta(days=1)


def prepare_on(c: ClientContract) -> date:
    return c.renewal_date - timedelta(days=c.notice_days)


def _has_quote(c: ClientContract) -> bool:
    return c.quote_for == c.renewal_date


def due(db: Session, today: date, company_id: int | None = None, force: bool = False) -> list[ClientContract]:
    """Contrats dont le devis est à préparer : dans le délai (ou tous avec `force`), sans devis
    pour cette échéance. Avec `force`, un devis supprimé entre-temps est refait."""
    stmt = select(ClientContract).where(ClientContract.active.is_(True))
    if company_id is not None:
        stmt = stmt.where(ClientContract.company_id == company_id)
    out = []
    for c in db.scalars(stmt.order_by(ClientContract.renewal_date)):
        if _has_quote(c) and (c.quote_id or not force):
            continue
        if force or prepare_on(c) <= today:
            out.append(c)
    return out


def prepare(
    db: Session,
    today: date | None = None,
    company_id: int | None = None,
    force: bool = False,
    by: str = "hub",
) -> list[BillingDoc]:
    """Crée un brouillon de devis par client pour ses contrats à renouveler."""
    today = today or date.today()
    groups: dict[int, list[ClientContract]] = {}
    for c in due(db, today, company_id, force):
        groups.setdefault(c.company_id, []).append(c)
    docs = []
    for cid, contracts in groups.items():
        company = db.get(Company, cid)
        first = min(c.renewal_date for c in contracts)
        lines = [
            LineIn(
                description=f"{c.name} – du {c.renewal_date:%d/%m/%Y} au {period_end(c.renewal_date, c.period):%d/%m/%Y}",
                quantity=c.quantity,
                unit_price=c.unit_price,
                vat_rate=c.vat_rate,
            )
            for c in contracts
        ]
        doc = billing.create_doc(
            db,
            DocIn(
                kind="quote",
                company_id=cid,
                title=f"Renouvellement {first.year} – {company.name if company else ''}".strip(" –")[:200],
                issue_date=today,
                due_date=max(first, today),
                notes="Renouvellement des services ci-dessous pour la période indiquée.",
                lines=lines,
            ),
            by,
        )
        for c in contracts:
            c.quote_id, c.quote_for = doc.id, c.renewal_date
        db.commit()
        create_alert(
            db,
            "renewal",
            "info",
            f"Devis de renouvellement prêt – {company.name if company else 'client'}",
            f"{len(contracts)} contrat(s), {doc.total_ht:.2f} € HT, échéance le {first:%d/%m/%Y}. "
            "Brouillon à relire dans Devis & factures, puis à envoyer vers Qonto.",
            dedupe_key=f"client-renewal:{doc.id}",
            cooldown_hours=24 * 3650,
        )
        docs.append(doc)
    return docs


def roll(db: Session, today: date | None = None) -> int:
    """Une fois l'échéance passée, le contrat passe à la période suivante (nouveau devis l'an prochain)."""
    today = today or date.today()
    moved = 0
    for c in db.scalars(
        select(ClientContract).where(ClientContract.active.is_(True), ClientContract.renewal_date < today)
    ):
        while c.renewal_date < today:
            c.renewal_date = add_months(c.renewal_date, PERIOD_MONTHS[c.period])
        moved += 1
    db.commit()
    return moved


def status(db: Session, c: ClientContract, today: date | None = None) -> dict:
    """État du renouvellement en cours, pour l'affichage."""
    today = today or date.today()
    doc = db.get(BillingDoc, c.quote_id) if c.quote_id and _has_quote(c) else None
    if doc is None:
        state = "deleted" if _has_quote(c) else "planned"
    elif doc.status in ("accepted", "refused"):
        state = doc.status
    elif qonto_billing.qonto_quote_id(doc) or doc.provider == "qonto":
        state = "qonto"
    else:
        state = "draft"
    days = (c.renewal_date - today).days
    return {
        "state": state,
        "prepare_on": prepare_on(c),
        "days_left": days,
        "urgent": c.active and days <= URGENT_DAYS and state != "accepted",
        "quote": {"id": doc.id, "number": doc.number, "total_ht": doc.total_ht, "status": doc.status}
        if doc
        else None,
    }


def upcoming(db: Session, days: int = 30, today: date | None = None) -> dict:
    """Pour le tableau de bord : renouvellements des `days` prochains jours et devis prêts."""
    today = today or date.today()
    rows = db.scalars(
        select(ClientContract).where(
            ClientContract.active.is_(True),
            ClientContract.renewal_date >= today,
            ClientContract.renewal_date <= today + timedelta(days=days),
        )
    ).all()
    ready = sum(1 for c in rows if status(db, c, today)["state"] in ("draft", "qonto", "accepted"))
    return {
        "count": len(rows),
        "with_quote": ready,
        "amount_ht": round(sum(c.unit_price * c.quantity for c in rows), 2),
    }
