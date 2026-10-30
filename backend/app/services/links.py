"""Liens automatiques entre les informations du Hub.

- Mail ↔ contact / société : par l'adresse de l'expéditeur, sinon par son domaine (site ou e-mails
  connus de la société). Les messageries grand public (gmail.com…) ne servent jamais à deviner.
- Prélèvement bancaire ↔ abonnement : le libellé du débit contient le fournisseur (ou le nom) de
  l'abonnement. Proposé à l'utilisateur, jamais appliqué tout seul.
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Contact, Subscription, Transaction

PUBLIC_DOMAINS = {
    "gmail.com", "googlemail.com", "outlook.com", "outlook.fr", "hotmail.com", "hotmail.fr", "live.com",
    "live.fr", "msn.com", "yahoo.com", "yahoo.fr", "icloud.com", "me.com", "orange.fr", "wanadoo.fr",
    "free.fr", "sfr.fr", "neuf.fr", "laposte.net", "bbox.fr", "aol.com", "proton.me", "protonmail.com", "gmx.fr", "gmx.com",
}  # fmt: skip


def domain_of(value: str) -> str:
    """Domaine d'un e-mail ou d'une URL, sans « www. »."""
    v = (value or "").strip().lower()
    if "@" in v:
        v = v.rsplit("@", 1)[1]
    v = re.sub(r"^[a-z]+://", "", v).split("/")[0].split(":")[0]
    return v.removeprefix("www.")


@dataclass
class Directory:
    by_email: dict[str, tuple[int, int | None]] = field(default_factory=dict)  # email -> (contact, société)
    by_domain: dict[str, int] = field(default_factory=dict)  # domaine -> société
    names: dict[int, str] = field(default_factory=dict)

    def match(self, email: str) -> dict:
        e = (email or "").strip().lower()
        if e in self.by_email:
            contact_id, company_id = self.by_email[e]
            return {
                "contact_id": contact_id,
                "company_id": company_id,
                "company_name": self.names.get(company_id or 0, ""),
            }
        company_id = self.by_domain.get(domain_of(e))
        return {
            "contact_id": None,
            "company_id": company_id,
            "company_name": self.names.get(company_id or 0, ""),
        }


def directory(db: Session) -> Directory:
    d = Directory()
    for c in db.scalars(select(Company)):
        d.names[c.id] = c.name
        for v in (c.website, c.email):
            dom = domain_of(v)
            if dom and dom not in PUBLIC_DOMAINS:
                d.by_domain.setdefault(dom, c.id)
    for ct in db.scalars(select(Contact).where(Contact.email != "")):
        d.by_email[ct.email.lower()] = (ct.id, ct.company_id)
        dom = domain_of(ct.email)
        if ct.company_id and dom and dom not in PUBLIC_DOMAINS:
            d.by_domain.setdefault(dom, ct.company_id)
    return d


def _words(s: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", (s or "").lower()) if len(w) >= 3]


def subscription_suggestions(db: Session, limit: int = 20) -> list[dict]:
    """Débits des 13 derniers mois qui ressemblent à un abonnement mais n'y sont pas rattachés."""
    since = date.today() - timedelta(days=400)
    debits = db.scalars(select(Transaction).where(Transaction.amount < 0, Transaction.tx_date >= since)).all()
    out: list[dict] = []
    for s in db.scalars(select(Subscription).where(Subscription.active.is_(True))):
        keys = _words(s.vendor) or _words(s.name)
        if not keys:
            continue
        linked = {t.id for t in s.transactions}
        for t in debits:
            if t.id in linked:
                continue
            label = set(_words(t.label))
            if keys[0] in label or all(k in label for k in keys[:2]):
                out.append(
                    {
                        "subscription_id": s.id,
                        "subscription_name": s.name,
                        "transaction_id": t.id,
                        "label": t.label,
                        "date": t.tx_date,
                        "amount": float(t.amount),
                    }
                )
    out.sort(key=lambda x: x["date"], reverse=True)
    return out[:limit]
