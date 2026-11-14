"""Suivi de l'argent : catégories des mouvements, tableau de bord, rentabilité par client,
justificatifs manquants, rapprochement des encaissements et export pour l'expert-comptable.

Tout est calculé à partir des mouvements bancaires (Qonto) et des documents synchronisés : le Hub
n'émet rien et ne paie rien.
"""

import csv
import io
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    BillingDoc,
    Budget,
    CategoryRule,
    Company,
    Employee,
    Payment,
    TimeEntry,
    Transaction,
)
from app.services import treasury
from app.services.alerts import create_alert

INCOME = "Encaissements clients"
INTERNAL = "Virements internes"
OTHER = "Autre"
CATEGORIES = [
    "Hébergement & domaines",
    "Logiciels & abonnements",
    "Salaires & charges sociales",
    "Impôts & taxes",
    "Frais bancaires",
    "Déplacements & repas",
    "Matériel",
    "Sous-traitance",
    "Marketing & communication",
    "Loyer & bureaux",
    "Honoraires (comptable, juridique)",
    "Assurances",
    "Notes de frais",
    INCOME,
    INTERNAL,
    OTHER,
]
# Catégories sans justificatif à fournir (prélèvements officiels, frais de la banque…).
NO_RECEIPT = {"Impôts & taxes", "Salaires & charges sociales", "Frais bancaires", INTERNAL, "Notes de frais"}

# Règles intégrées : mot du libellé (sans casse) → catégorie. Les règles de l'utilisateur passent avant.
BUILTIN_RULES: list[tuple[str, str]] = [
    *[
        (k, "Hébergement & domaines")
        for k in (
            "ovh",
            "o2switch",
            "hetzner",
            "scaleway",
            "gandi",
            "ionos",
            "infomaniak",
            "amazon web services",
            "aws ",
            "cloudflare",
            "vercel",
            "netlify",
            "digitalocean",
        )
    ],
    *[
        (k, "Logiciels & abonnements")
        for k in (
            "google",
            "microsoft",
            "adobe",
            "notion",
            "slack",
            "github",
            "gitlab",
            "figma",
            "canva",
            "atlassian",
            "dropbox",
            "zoom",
            "jetbrains",
            "1password",
            "bitwarden",
            "mailchimp",
            "brevo",
            "openai",
            "anthropic",
        )
    ],
    *[
        (k, "Impôts & taxes")
        for k in ("dgfip", "impot", "impôt", "tresor public", "trésor public", "cfe ", "tva ")
    ],
    *[(k, "Salaires & charges sociales") for k in ("urssaf", "payfit", "salaire", "retraite", "mutuelle")],
    *[
        (k, "Déplacements & repas")
        for k in ("sncf", "uber", "blablacar", "air france", "airbnb", "booking", "restaurant", "total ")
    ],
    *[(k, "Matériel") for k in ("ldlc", "materiel.net", "boulanger", "fnac", "apple store")],
    *[(k, "Assurances") for k in ("axa", "hiscox", "allianz", "maif", "macif", "assurance")],
    *[(k, "Honoraires (comptable, juridique)") for k in ("expert-compt", "comptab", "avocat", "infogreffe")],
    *[(k, "Frais bancaires") for k in ("qonto", "frais bancaire", "commission")],
]
# Catégories Qonto (ou types d'opération) → catégorie du Hub.
QONTO_MAP = {
    "qonto_fee": "Frais bancaires",
    "fees": "Frais bancaires",
    "atm": "Frais bancaires",
    "hotel_and_lodging": "Déplacements & repas",
    "transport": "Déplacements & repas",
    "restaurant_and_bar": "Déplacements & repas",
    "food_and_grocery": "Déplacements & repas",
    "online_service": "Logiciels & abonnements",
    "it_and_electronics": "Matériel",
    "hardware_and_equipment": "Matériel",
    "tax": "Impôts & taxes",
    "insurance": "Assurances",
    "legal_and_accounting": "Honoraires (comptable, juridique)",
    "marketing": "Marketing & communication",
    "office_rental": "Loyer & bureaux",
    "salary": "Salaires & charges sociales",
    "payroll": "Salaires & charges sociales",
}


# ---------- Catégories ----------
def guess_category(tx: Transaction, rules: list[CategoryRule]) -> str:
    label = f" {tx.label.lower()} "
    for r in rules:
        if r.pattern.strip() and r.pattern.strip().lower() in label:
            return r.category
    for word, cat in BUILTIN_RULES:
        if word in label:
            return cat
    if (mapped := QONTO_MAP.get((tx.category or "").lower()) or QONTO_MAP.get(tx.operation_type or "")) and (
        tx.amount < 0 or mapped == INTERNAL
    ):
        return mapped
    return INCOME if tx.amount > 0 else OTHER


def user_rules(db: Session) -> list[CategoryRule]:
    # Les motifs les plus longs (les plus précis) d'abord.
    return sorted(db.scalars(select(CategoryRule)), key=lambda r: -len(r.pattern))


def categorize(db: Session, txs: list[Transaction] | None = None, force: bool = False) -> int:
    """Classe les mouvements non classés (ou tous, sauf choix manuels, si `force`)."""
    rules = user_rules(db)
    txs = txs if txs is not None else list(db.scalars(select(Transaction)))
    changed = 0
    for tx in txs:
        if tx.category_locked or (tx.hub_category and not force):
            continue
        cat = guess_category(tx, rules)
        if cat != tx.hub_category:
            tx.hub_category, changed = cat, changed + 1
    db.commit()
    return changed


# ---------- Périodes ----------
def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def months_back(n: int, today: date | None = None) -> list[str]:
    """Les `n` derniers mois, du plus ancien au mois en cours inclus."""
    today = today or date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out[::-1]


def month_start(key: str) -> date:
    y, m = key.split("-")
    return date(int(y), int(m), 1)


def _txs_since(db: Session, start: date) -> list[Transaction]:
    return list(db.scalars(select(Transaction).where(Transaction.tx_date >= start)))


# ---------- Vue d'ensemble ----------
def overview(db: Session, months: int = 12, today: date | None = None) -> dict:
    today = today or date.today()
    keys = months_back(months, today)
    first = month_start(keys[0])
    last_year_keys = [f"{int(k[:4]) - 1}{k[4:]}" for k in keys]
    rows = {k: {"month": k, "income": 0.0, "expense": 0.0} for k in keys + last_year_keys}
    for tx in _txs_since(db, month_start(last_year_keys[0])):
        if (tx.hub_category or "") == INTERNAL or (r := rows.get(month_key(tx.tx_date))) is None:
            continue
        r["income" if tx.amount > 0 else "expense"] += abs(tx.amount)
    series = []
    for k, ly in zip(keys, last_year_keys, strict=True):
        r, p = rows[k], rows[ly]
        series.append(
            {
                "month": k,
                "income": round(r["income"], 2),
                "expense": round(r["expense"], 2),
                "net": round(r["income"] - r["expense"], 2),
                "income_last_year": round(p["income"], 2),
                "expense_last_year": round(p["expense"], 2),
            }
        )
    current = series[-1]
    full = series[-4:-1] or series[:1]  # 3 derniers mois complets
    avg_net = round(sum(s["net"] for s in full) / len(full), 2)
    balance = round(treasury.current_balance(db), 2)
    runway = round(balance / -avg_net, 1) if avg_net < 0 and balance > 0 else None
    return {
        "series": series,
        "since": first,
        "balance": balance,
        "current": current,
        "avg_net_3m": avg_net,
        "runway_months": runway,
        "vat": vat_estimate(db, today),
        "uncategorized": sum(1 for tx in _txs_since(db, first) if not tx.hub_category),
    }


def _quarter_start(d: date) -> date:
    return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)


def vat_estimate(db: Session, today: date | None = None) -> dict:
    """TVA du trimestre en cours : collectée sur les encaissements de factures (prestations de
    services : TVA due à l'encaissement), moins la TVA déductible des dépenses connue de Qonto."""
    today = today or date.today()
    start = _quarter_start(today)
    collected = 0.0
    for p in db.scalars(select(Payment).where(Payment.paid_on >= start, Payment.paid_on <= today)):
        doc = p.doc
        if doc and doc.kind == "invoice" and doc.total_ttc:
            collected += float(p.amount) * doc.total_vat / doc.total_ttc
    deductible = sum(
        abs(tx.vat_amount or 0)
        for tx in db.scalars(
            select(Transaction).where(
                Transaction.tx_date >= start, Transaction.tx_date <= today, Transaction.amount < 0
            )
        )
    )
    return {
        "since": start,
        "collected": round(collected, 2),
        "deductible": round(deductible, 2),
        "due": round(collected - deductible, 2),
    }


# ---------- Dépenses par catégorie et budgets ----------
def by_category(db: Session, months: int = 6, today: date | None = None) -> dict:
    today = today or date.today()
    keys = months_back(months, today)
    budgets = {b.category: float(b.monthly_amount) for b in db.scalars(select(Budget))}
    table: dict[str, dict[str, float]] = {}
    for tx in _txs_since(db, month_start(keys[0])):
        if tx.amount >= 0 or (tx.hub_category or OTHER) == INTERNAL:
            continue
        cat = tx.hub_category or OTHER
        table.setdefault(cat, {})
        table[cat][month_key(tx.tx_date)] = table[cat].get(month_key(tx.tx_date), 0) - tx.amount
    cur = keys[-1]
    rows = []
    for cat in sorted(set(table) | set(budgets), key=lambda c: -sum(table.get(c, {}).values())):
        per = {k: round(table.get(cat, {}).get(k, 0), 2) for k in keys}
        budget = budgets.get(cat)
        rows.append(
            {
                "category": cat,
                "months": per,
                "total": round(sum(per.values()), 2),
                "average": round(sum(per.values()) / len(keys), 2),
                "budget": budget,
                "over_budget": bool(budget and per[cur] > budget),
            }
        )
    return {"months": keys, "rows": rows}


def check_budgets(db: Session, today: date | None = None) -> int:
    """Alerte (une fois par mois et par catégorie) quand les dépenses dépassent le budget."""
    today = today or date.today()
    key = month_key(today)
    n = 0
    for row in by_category(db, 1, today)["rows"]:
        if row["over_budget"]:
            spent = row["months"][key]
            alert = create_alert(
                db,
                "budget",
                "warning",
                f"Budget dépassé : {row['category']}",
                f"{spent:.2f} € dépensés ce mois-ci pour un budget de {row['budget']:.2f} €.",
                dedupe_key=f"budget:{row['category']}:{key}",
                cooldown_hours=24 * 40,
            )
            n += alert is not None
    return n


# ---------- Rentabilité par client ----------
def clients(db: Session, months: int = 12, today: date | None = None) -> list[dict]:
    today = today or date.today()
    start = month_start(months_back(months, today)[0])
    cost_h = {e.email.lower(): float(e.daily_cost) / 7 for e in db.scalars(select(Employee)) if e.email}
    rows: dict[int, dict] = {}

    def row(cid: int) -> dict:
        return rows.setdefault(
            cid,
            {"invoiced_ht": 0.0, "collected": 0.0, "outstanding": 0.0, "hours": 0.0, "time_cost": 0.0},
        )

    for d in db.scalars(
        select(BillingDoc).where(
            BillingDoc.kind == "invoice",
            BillingDoc.status.in_(("sent", "paid")),
            BillingDoc.issue_date >= start,
            BillingDoc.company_id.is_not(None),
        )
    ):
        r = row(d.company_id)
        r["invoiced_ht"] += d.total_ht
        r["collected"] += float(d.amount_paid or 0)
        r["outstanding"] += max(d.total_ttc - float(d.amount_paid or 0), 0)
    for t in db.scalars(
        select(TimeEntry).where(TimeEntry.work_date >= start, TimeEntry.company_id.is_not(None))
    ):
        r = row(t.company_id)
        r["hours"] += t.hours
        r["time_cost"] += t.hours * cost_h.get(t.user_email.lower(), 0)
    names = {c.id: c.name for c in db.scalars(select(Company))}
    out = []
    for cid, r in rows.items():
        margin = r["invoiced_ht"] - r["time_cost"]
        out.append(
            {
                "company_id": cid,
                "company": names.get(cid, f"Société {cid}"),
                **{k: round(v, 2) for k, v in r.items()},
                "margin": round(margin, 2),
                "margin_pct": round(100 * margin / r["invoiced_ht"], 1) if r["invoiced_ht"] else None,
                "hourly_value": round(r["invoiced_ht"] / r["hours"], 2) if r["hours"] else None,
            }
        )
    out.sort(key=lambda x: -x["margin"])
    return out


# ---------- Justificatifs et rapprochement ----------
def missing_receipts(db: Session, days: int = 90, today: date | None = None) -> list[Transaction]:
    """Dépenses sans justificatif dans Qonto (hors impôts, salaires, frais bancaires, virements internes)."""
    today = today or date.today()
    return [
        tx
        for tx in db.scalars(
            select(Transaction)
            .where(Transaction.tx_date >= today - timedelta(days=days), Transaction.amount < 0)
            .order_by(Transaction.tx_date.desc())
        )
        if tx.attachment_count == 0
        and not tx.attachment_lost
        and (tx.attachment_required or tx.operation_type == "card")
        and (tx.hub_category or OTHER) not in NO_RECEIPT
    ]


def suggest_invoice(db: Session, tx: Transaction) -> BillingDoc | None:
    """Facture dont le montant TTC correspond à l'encaissement (à 1 centime près), émise avant."""
    candidates = [
        d
        for d in db.scalars(
            select(BillingDoc).where(
                BillingDoc.kind == "invoice",
                BillingDoc.status.in_(("sent", "paid")),
                BillingDoc.issue_date <= tx.tx_date,
                BillingDoc.issue_date >= tx.tx_date - timedelta(days=180),
            )
        )
        if abs(d.total_ttc - tx.amount) < 0.011
        and not db.scalar(select(Transaction.id).where(Transaction.billing_doc_id == d.id))
    ]
    if not candidates:
        return None
    label = tx.label.lower()
    names = {c.id: c.name.lower() for c in db.scalars(select(Company))}
    # Le nom du client ou le numéro de facture dans le libellé départage les candidats.
    candidates.sort(
        key=lambda d: (
            not ((d.number or "").lower() in label and d.number),
            not (d.company_id and names.get(d.company_id, "~") in label),
            abs((tx.tx_date - d.issue_date).days),
        )
    )
    return candidates[0]


def reconciliation(db: Session, days: int = 120, today: date | None = None) -> dict:
    today = today or date.today()
    incomes = list(
        db.scalars(
            select(Transaction)
            .where(
                Transaction.tx_date >= today - timedelta(days=days),
                Transaction.amount > 0,
                Transaction.billing_doc_id.is_(None),
            )
            .order_by(Transaction.tx_date.desc())
        )
    )
    unmatched = []
    for tx in incomes:
        if (tx.hub_category or INCOME) == INTERNAL:
            continue
        sug = suggest_invoice(db, tx)
        unmatched.append((tx, sug))
    matched = list(
        db.scalars(
            select(Transaction)
            .where(
                Transaction.billing_doc_id.is_not(None), Transaction.tx_date >= today - timedelta(days=days)
            )
            .order_by(Transaction.tx_date.desc())
        )
    )
    return {"unmatched": unmatched, "matched": matched}


def export_csv(db: Session, start: date, end: date) -> str:
    """Mouvements de la période pour l'expert-comptable (séparateur « ; », ouvrable dans Excel)."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Date", "Libellé", "Montant", "Catégorie", "TVA", "Justificatif", "Facture rapprochée"])
    for tx in db.scalars(
        select(Transaction)
        .where(Transaction.tx_date >= start, Transaction.tx_date <= end)
        .order_by(Transaction.tx_date, Transaction.id)
    ):
        doc = db.get(BillingDoc, tx.billing_doc_id) if tx.billing_doc_id else None
        w.writerow(
            [
                tx.tx_date.strftime("%d/%m/%Y"),
                tx.label,
                f"{tx.amount:.2f}".replace(".", ","),
                tx.hub_category or "",
                f"{abs(tx.vat_amount):.2f}".replace(".", ",") if tx.vat_amount else "",
                "oui" if tx.attachment_count else ("non requis" if tx.amount > 0 else "non"),
                (doc.number or f"n°{doc.id}") if doc else "",
            ]
        )
    return "﻿" + buf.getvalue()  # BOM : accents corrects dans Excel
