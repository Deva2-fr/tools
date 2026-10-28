"""Trésorerie : solde actuel et prévision (factures à encaisser, impôts, abonnements)."""

import csv
import io
import re
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BankAccount, BillingDoc, Company, Subscription, TaxDeadline, Transaction
from app.services import billing
from app.services.renewals import occurrences

LATE_PAYMENT_DELAY = 10  # une facture en retard est supposée payée sous 10 jours


def current_balance(db: Session) -> float:
    initial = db.scalar(select(func.coalesce(func.sum(BankAccount.initial_balance), 0))) or 0
    moves = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0))) or 0
    return round(float(initial) + float(moves), 2)


def forecast(db: Session, days: int = 90, today: date | None = None) -> dict:
    today = today or date.today()
    end = today + timedelta(days=days)
    events: list[dict] = []
    names = {c.id: c.name for c in db.scalars(select(Company))}

    for d in db.scalars(select(BillingDoc).where(BillingDoc.kind == "invoice", BillingDoc.status == "sent")):
        left = billing.remaining(d)
        if left <= 0:
            continue
        when = d.due_date or today
        if when < today:
            when = today + timedelta(days=LATE_PAYMENT_DELAY)
        if when <= end:
            events.append(
                {
                    "date": when,
                    "label": f"Encaissement {d.number} – {names.get(d.company_id, '')}".strip(" –"),
                    "amount": left,
                    "type": "invoice",
                }
            )
    for t in db.scalars(
        select(TaxDeadline).where(TaxDeadline.status == "todo", TaxDeadline.amount.is_not(None))
    ):
        when = max(t.due_date, today)
        if when <= end:
            events.append({"date": when, "label": t.title, "amount": -float(t.amount), "type": "tax"})
    for s in db.scalars(select(Subscription).where(Subscription.active.is_(True), Subscription.cost > 0)):
        for when in occurrences(s, today, end):
            events.append(
                {
                    "date": when,
                    "label": f"Renouvellement {s.name}",
                    "amount": -float(s.cost) * 1.2,
                    "type": "subscription",
                }
            )
    events.sort(key=lambda e: e["date"])

    balance = current_balance(db)
    series, running, i = [], balance, 0
    for offset in range(0, days + 1, 7):
        horizon = today + timedelta(days=offset)
        while i < len(events) and events[i]["date"] <= horizon:
            running += events[i]["amount"]
            i += 1
        series.append({"date": horizon, "balance": round(running, 2)})
    lowest = min(p["balance"] for p in series)
    return {
        "balance": balance,
        "events": events,
        "series": series,
        "lowest": lowest,
        "end_balance": series[-1]["balance"],
    }


_DATE_FORMATS = (
    ("%d/%m/%Y", r"^\d{1,2}/\d{1,2}/\d{4}$"),
    ("%Y-%m-%d", r"^\d{4}-\d{2}-\d{2}$"),
    ("%d-%m-%Y", r"^\d{1,2}-\d{1,2}-\d{4}$"),
    ("%d/%m/%y", r"^\d{1,2}/\d{1,2}/\d{2}$"),
)


def parse_date(raw: str) -> date:
    from datetime import datetime

    raw = raw.strip()
    for fmt, pattern in _DATE_FORMATS:
        if re.match(pattern, raw):
            return datetime.strptime(raw, fmt).date()
    raise ValueError(f"date illisible « {raw} »")


def parse_amount(raw: str) -> float:
    s = raw.strip().replace(" ", "").replace(" ", "").replace("€", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    return float(s)


def import_csv(db: Session, account_id: int, text: str) -> dict:
    """Colonnes reconnues (insensible à la casse) : date, libellé/label, montant/amount — ou débit/crédit."""
    text = text.lstrip("﻿")
    try:
        dialect = csv.Sniffer().sniff(text[:2000], delimiters=";,\t")
    except csv.Error:
        dialect = csv.excel
    created, errors = 0, []
    for i, raw in enumerate(csv.DictReader(io.StringIO(text), dialect=dialect), start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        try:
            d = parse_date(row.get("date") or row.get("date opération") or row.get("date operation") or "")
            label = (
                row.get("libellé") or row.get("libelle") or row.get("label") or row.get("description") or ""
            )
            if "montant" in row or "amount" in row:
                amount = parse_amount(row.get("montant") or row.get("amount") or "")
            else:
                amount = (parse_amount(row["crédit"] or "0") if row.get("crédit") else 0) - (
                    parse_amount(row["débit"] or "0") if row.get("débit") else 0
                )
            if not label:
                raise ValueError("libellé manquant")
        except (ValueError, KeyError) as exc:
            errors.append(f"ligne {i} : {exc}")
            continue
        dup = db.scalar(
            select(Transaction.id).where(
                Transaction.account_id == account_id,
                Transaction.tx_date == d,
                Transaction.label == label,
                Transaction.amount == amount,
            )
        )
        if dup:
            continue
        db.add(Transaction(account_id=account_id, tx_date=d, label=label[:300], amount=amount))
        created += 1
    db.commit()
    return {"created": created, "errors": errors[:20]}
