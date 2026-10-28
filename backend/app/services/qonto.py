"""Synchronisation des comptes Qonto (API Business v2, lecture seule) vers la trésorerie du Hub.

Identifiants : Qonto > Paramètres > Intégrations et partenariats > Clé API (identifiant + clé secrète).
Le Hub ne fait que LIRE : comptes, soldes et transactions réglées.
"""

from datetime import date, timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.models import BankAccount, Transaction
from app.services import integrations

API_URL = "https://thirdparty.qonto.com/v2"
FIRST_SYNC_DAYS = 90  # historique récupéré à la première synchronisation
OVERLAP_DAYS = (
    3  # on relit un peu en arrière (opérations réglées tardivement), sans doublon grâce à external_id
)


class QontoError(RuntimeError):
    """Qonto non configuré, identifiants refusés ou service injoignable (message affichable)."""


def is_configured(db: Session) -> bool:
    return bool(integrations.get(db, "qonto_login") and integrations.get(db, "qonto_secret_key"))


def _client(db: Session) -> httpx.Client:
    login, secret = integrations.get(db, "qonto_login"), integrations.get(db, "qonto_secret_key")
    if not (login and secret):
        raise QontoError("Qonto n'est pas configuré (Paramètres > Intégrations > Qonto).")
    return httpx.Client(base_url=API_URL, timeout=20, headers={"Authorization": f"{login}:{secret}"})


def _get(client: httpx.Client, path: str, params=None) -> dict:
    try:
        r = client.get(path, params=params)
    except httpx.HTTPError as exc:
        raise QontoError("Qonto est momentanément injoignable.") from exc
    if r.status_code in (401, 403):
        raise QontoError("Qonto refuse les identifiants : vérifiez l'identifiant et la clé secrète.")
    if r.status_code == 429:
        raise QontoError("Trop de requêtes vers Qonto : réessayez dans une minute.")
    if r.status_code >= 400:
        raise QontoError(f"Erreur Qonto ({r.status_code}).")
    return r.json()


def organization(client: httpx.Client) -> dict:
    return _get(client, "/organization").get("organization") or {}


def transactions(client: httpx.Client, iban: str, since) -> list[dict]:
    """Transactions réglées (status=completed) depuis `since`, toutes pages confondues."""
    out, page = [], 1
    while page and page <= 50:
        data = _get(
            client,
            "/transactions",
            params={
                "iban": iban,
                "status[]": "completed",
                "settled_at_from": since.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "sort_by": "settled_at:asc",
                "per_page": 100,
                "current_page": page,
            },
        )
        out += data.get("transactions") or []
        page = (data.get("meta") or {}).get("next_page")
    return out


def _amount(t: dict) -> float:
    value = t.get("amount")
    if value is None and t.get("amount_cents") is not None:
        value = t["amount_cents"] / 100
    value = abs(float(value or 0))
    return -value if t.get("side") == "debit" else value


def _label(t: dict) -> str:
    parts = [t.get("label") or t.get("operation_type") or "Opération Qonto"]
    if t.get("reference"):
        parts.append(f"({t['reference']})")
    return " ".join(parts)[:300]


def sync(db: Session, client: httpx.Client | None = None) -> dict:
    """Importe les nouvelles transactions et aligne le solde de chaque compte sur celui de Qonto."""
    own = client is None
    client = client or _client(db)
    try:
        org = organization(client)
        created, accounts = 0, []
        for acc in org.get("bank_accounts") or []:
            if acc.get("status") not in (None, "active"):
                continue
            ext_id = str(acc.get("id") or acc.get("slug") or acc.get("iban"))
            account = db.scalar(select(BankAccount).where(BankAccount.external_id == ext_id))
            if not account:
                account = BankAccount(
                    name=f"Qonto – {acc.get('name') or acc.get('iban', '')[-4:]}"[:120],
                    iban=acc.get("iban", ""),
                    provider="qonto",
                    external_id=ext_id,
                    initial_balance=0,
                )
                db.add(account)
                db.flush()
            since = (
                (account.last_synced_at - timedelta(days=OVERLAP_DAYS))
                if account.last_synced_at
                else (utcnow() - timedelta(days=FIRST_SYNC_DAYS))
            )
            for t in transactions(client, acc.get("iban", ""), since):
                tid = str(t.get("id") or t.get("transaction_id") or "")
                when = (t.get("settled_at") or t.get("emitted_at") or "")[:10]
                if (
                    not tid
                    or not when
                    or db.scalar(select(Transaction.id).where(Transaction.external_id == tid))
                ):
                    continue
                db.add(
                    Transaction(
                        account_id=account.id,
                        tx_date=date.fromisoformat(when),
                        label=_label(t),
                        amount=_amount(t),
                        category=(t.get("category") or t.get("operation_type") or "")[:80],
                        external_id=tid,
                    )
                )
                created += 1
            db.flush()
            # Solde réel Qonto = solde de départ + somme des mouvements connus : on recale le solde de départ.
            balance = acc.get("balance")
            if balance is None and acc.get("balance_cents") is not None:
                balance = acc["balance_cents"] / 100
            moves = db.scalar(
                select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                    Transaction.account_id == account.id
                )
            )
            if balance is not None:
                account.initial_balance = round(float(balance) - float(moves or 0), 2)
            account.last_synced_at = utcnow()
            accounts.append({"name": account.name, "balance": balance})
        db.commit()
        return {"accounts": accounts, "created": created}
    finally:
        if own:
            client.close()


def test_connection(db: Session) -> str:
    with _client(db) as client:
        org = organization(client)
    n = len(org.get("bank_accounts") or [])
    return f"Connexion OK – {org.get('legal_name') or org.get('slug') or 'organisation'} : {n} compte(s)."
