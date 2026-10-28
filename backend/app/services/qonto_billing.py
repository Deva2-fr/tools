"""Import des devis et factures clients depuis Qonto (API Business v2, lecture seule).

Les documents sont créés et émis dans Qonto ; le Hub les recopie (client, lignes, montants, statut,
lien vers le PDF Qonto) pour le suivi : CA, reste à encaisser, retards, relances, trésorerie.
Un document importé ne se modifie pas dans le Hub : il est remis à jour à chaque synchronisation.
"""

from datetime import date

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.models import BillingDoc, BillingLine, Company, Payment
from app.services import integrations
from app.services.qonto import QontoError, _client

INVOICE_STATUS = {"draft": "draft", "unpaid": "sent", "paid": "paid", "canceled": "cancelled"}
QUOTE_STATUS = {"pending_approval": "sent", "approved": "accepted", "canceled": "refused"}
MAX_PAGES = 50


def _list(client: httpx.Client, path: str, key: str, label: str) -> list[dict]:
    out, page = [], 1
    while page and page <= MAX_PAGES:
        try:
            r = client.get(path, params={"per_page": 100, "current_page": page})
        except httpx.HTTPError as exc:
            raise QontoError("Qonto est momentanément injoignable.") from exc
        if r.status_code == 401:
            raise QontoError("Qonto refuse les identifiants : vérifiez l'identifiant et la clé secrète.")
        if r.status_code == 403:
            raise QontoError(
                f"La clé API Qonto n'a pas accès aux {label} : vérifiez ses droits dans Qonto "
                "(Paramètres > Intégrations et partenariats > Clé API)."
            )
        if r.status_code == 429:
            raise QontoError("Trop de requêtes vers Qonto : réessayez dans une minute.")
        if r.status_code >= 400:
            raise QontoError(f"Erreur Qonto sur les {label} ({r.status_code}).")
        data = r.json()
        out += data.get(key) or []
        page = (data.get("meta") or {}).get("next_page")
    return out


def _amount(obj: dict, key: str) -> float | None:
    """Montant Qonto : {"value": "12.50", "currency": "EUR"}, nombre/chaîne, ou <clé>_cents."""
    v = obj.get(key)
    if isinstance(v, dict):
        v = v.get("value")
    if v is None and obj.get(f"{key}_cents") is not None:
        return round(float(obj[f"{key}_cents"]) / 100, 2)
    try:
        return round(float(v), 2) if v is not None else None
    except (TypeError, ValueError):
        return None


def _rate(v) -> float:
    """Taux de TVA : Qonto l'envoie en fraction (« 0.2 ») ; on stocke en pourcentage (20)."""
    try:
        r = float(v or 0)
    except (TypeError, ValueError):
        return 0.0
    return round(r * 100 if r <= 1 else r, 2)


def _day(v) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _client_name(c: dict) -> str:
    name = (c.get("name") or "").strip()
    if not name:
        name = " ".join(x for x in (c.get("first_name"), c.get("last_name")) if x).strip()
    return name[:200]


def _company(db: Session, c: dict | None) -> int | None:
    """Retrouve le client du CRM (n° de TVA, puis nom), sinon le crée comme client."""
    if not c:
        return None
    name = _client_name(c)
    vat = (c.get("vat_number") or "").replace(" ", "").upper()[:30]
    company = None
    if vat:
        company = db.scalar(select(Company).where(Company.vat_number == vat))
    if not company and name:
        company = db.scalar(select(Company).where(func.lower(Company.name) == name.lower()))
    if not company:
        if not name:
            return None
        addr = c.get("billing_address") or c.get("address") or {}
        if isinstance(addr, str):
            addr = {"street_address": addr}
        company = Company(
            name=name,
            kind="client",
            vat_number=vat,
            siret=(c.get("tax_identification_number") or "").replace(" ", "")[:20],
            email=(c.get("email") or "")[:255],
            address=(addr.get("street_address") or "")[:300],
            postal_code=(addr.get("zip_code") or "")[:12],
            city=(addr.get("city") or "")[:120],
            country="France" if (addr.get("country_code") or "FR").upper() == "FR" else addr["country_code"],
            notes="Créé automatiquement depuis Qonto",
        )
        db.add(company)
        db.flush()
    return company.id


def _number(db: Session, doc: BillingDoc, number: str) -> str | None:
    """Garde le numéro Qonto ; préfixe « Q- » s'il est déjà pris par un document du Hub."""
    number = (number or "").strip()[:30]
    if not number:
        return None
    other = db.scalar(select(BillingDoc.id).where(BillingDoc.number == number, BillingDoc.id != doc.id))
    return f"Q-{number}"[:30] if other else number


def _upsert(db: Session, kind: str, item: dict) -> bool:
    ext_id = f"{kind}:{item.get('id')}"
    doc = db.scalar(select(BillingDoc).where(BillingDoc.external_id == ext_id))
    created = doc is None
    if created:
        doc = BillingDoc(kind=kind, provider="qonto", external_id=ext_id, created_by="Qonto")
    with db.no_autoflush:  # les recherches (client, numéro) ne doivent pas insérer un document incomplet
        _fill(db, doc, kind, item)
    if created:
        db.add(doc)
    _sync_payment(db, doc, kind, item)
    return created


def _fill(db: Session, doc: BillingDoc, kind: str, item: dict) -> None:
    statuses = INVOICE_STATUS if kind == "invoice" else QUOTE_STATUS
    doc.status = statuses.get(item.get("status") or "", "sent")
    doc.number = _number(db, doc, item.get("number") or "")
    doc.company_id = _company(db, item.get("client"))
    doc.issue_date = _day(item.get("issue_date")) or _day(item.get("created_at")) or date.today()
    doc.due_date = _day(item.get("due_date") if kind == "invoice" else item.get("expiry_date"))
    doc.external_url = (item.get("invoice_url") or item.get("quote_url") or "")[:500]
    doc.notes = (item.get("header") or item.get("footer") or "")[:2000]

    doc.lines.clear()
    for i, it in enumerate(item.get("items") or []):
        title = " – ".join(x for x in (it.get("title"), it.get("description")) if x) or "Prestation"
        try:
            qty = float(it.get("quantity") or 1)
        except (TypeError, ValueError):
            qty = 1.0
        doc.lines.append(
            BillingLine(
                position=i,
                description=title[:500],
                quantity=qty,
                unit_price=_amount(it, "unit_price") or 0,
                vat_rate=_rate(it.get("vat_rate")),
            )
        )
        doc.title = doc.title or (it.get("title") or "")[:200]

    ttc = _amount(item, "total_amount")
    vat = _amount(item, "vat_amount")
    if ttc is None:  # pas de total fourni : on le recalcule depuis les lignes
        from app.services.billing import compute_totals

        doc.total_ht, doc.total_vat, doc.total_ttc = compute_totals(doc.lines)
    else:
        doc.total_ttc, doc.total_vat = ttc, vat or 0
        doc.total_ht = round(ttc - (vat or 0), 2)


def _sync_payment(db: Session, doc: BillingDoc, kind: str, item: dict) -> None:
    """Un seul règlement « Qonto » couvrant la facture quand Qonto la marque payée."""
    db.flush()
    qonto_pay = [p for p in doc.payments if p.method == "Qonto"]
    if kind == "invoice" and doc.status == "paid":
        paid_on = _day(item.get("paid_at")) or doc.issue_date
        if qonto_pay:
            qonto_pay[0].amount, qonto_pay[0].paid_on = doc.total_ttc, paid_on
        else:
            doc.payments.append(Payment(paid_on=paid_on, amount=doc.total_ttc, method="Qonto"))
    else:
        for p in qonto_pay:
            doc.payments.remove(p)
    db.flush()
    doc.amount_paid = round(sum(float(p.amount) for p in doc.payments), 2)


def sync(db: Session, client: httpx.Client | None = None) -> dict:
    own = client is None
    client = client or _client(db)
    try:
        invoices = _list(client, "/client_invoices", "client_invoices", "factures clients")
        quotes = _list(client, "/quotes", "quotes", "devis")
        created = sum(_upsert(db, "invoice", i) for i in invoices if i.get("id"))
        created += sum(_upsert(db, "quote", q) for q in quotes if q.get("id"))
        db.commit()
        integrations.put(db, "qonto_billing_synced_at", utcnow().isoformat())
        return {"invoices": len(invoices), "quotes": len(quotes), "created": created}
    finally:
        if own:
            client.close()
