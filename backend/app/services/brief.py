"""Brief du matin et suggestions d'organisation.

Les faits et suggestions sont calculés directement dans la base (fiables, gratuits) ; l'IA ne fait que
rédiger le brief en quelques points à partir de ces faits. Résultat mis en cache une fois par jour et
par utilisateur. Sans clé API ou budget épuisé : brief rédigé automatiquement, sans IA.
"""

import json
from datetime import date, timedelta

import anthropic
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import is_manager
from app.models import (
    Activity,
    BillingDoc,
    Company,
    Contact,
    CopilotBrief,
    FileRecord,
    MailMessage,
    Opportunity,
    Subscription,
    Task,
    TaxDeadline,
    TimeEntry,
    User,
)
from app.services import billing, copilot, integrations, outlook

OPEN_STAGES = ("prospect", "contact", "quote", "negotiation")
SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "points": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "points"],
    "additionalProperties": False,
}
PROMPT = """Tu rédiges le brief du matin du Hub Deva2 (agence web) pour {name}.
À partir des faits ci-dessous (JSON), écris :
- headline : une phrase d'accroche (max 15 mots) qui dit ce qui compte le plus aujourd'hui ;
- points : 3 à 5 points courts et concrets, du plus urgent au moins urgent, avec les chiffres utiles
  (montants en €, nombres, dates). Pas de point vide ou générique ; s'il n'y a rien d'urgent, dis-le.
Français, direct, sans formule de politesse. N'invente rien : uniquement les faits fournis.

Faits :
{facts}"""


def _money(v: float) -> str:
    return f"{v:,.0f} €".replace(",", " ")


def suggestions(db: Session, user: User) -> list[dict]:
    """Idées d'organisation concrètes, chacune avec un lien et une question pour le copilote."""
    today = date.today()
    out: list[dict] = []
    mgr = is_manager(user)

    if mgr:
        stale = db.scalars(
            select(BillingDoc)
            .where(
                BillingDoc.kind == "quote",
                BillingDoc.status == "sent",
                BillingDoc.issue_date <= today - timedelta(days=10),
            )
            .order_by(BillingDoc.issue_date)
            .limit(3)
        ).all()
        for d in stale:
            name = db.get(Company, d.company_id).name if d.company_id else "le client"
            days = (today - d.issue_date).days
            out.append(
                {
                    "kind": "relance_devis",
                    "title": f"Relancer {name} : devis sans réponse depuis {days} jours",
                    "detail": f"{d.number or d.title} · {_money(d.total_ht)} HT",
                    "link": f"/facturation/{d.id}",
                    "ask": f"Prépare une relance pour le devis {d.number or d.id} de {name} (sans réponse depuis {days} jours) et propose une tâche.",
                }
            )
        invoices = db.scalars(
            select(BillingDoc).where(BillingDoc.kind == "invoice", BillingDoc.status == "sent")
        ).all()
        late = [d for d in invoices if billing.overdue(d)]
        if late:
            total = sum(billing.remaining(d) for d in late)
            out.append(
                {
                    "kind": "factures_retard",
                    "title": f"{len(late)} facture(s) en retard : {_money(total)} à encaisser",
                    "detail": "Relancez les clients concernés.",
                    "link": "/facturation",
                    "ask": "Liste les factures en retard par client et propose une tâche de relance pour chacune.",
                }
            )

    # Clients sans échange depuis 60 jours (journal d'activité ou mails).
    since = today - timedelta(days=60)
    for c in db.scalars(select(Company).where(Company.kind == "client").order_by(Company.name)).all():
        if len([s for s in out if s["kind"] == "client_silencieux"]) >= 3:
            break
        last_act = db.scalar(select(func.max(Activity.created_at)).where(Activity.company_id == c.id))
        emails = [e for e in db.scalars(select(Contact.email).where(Contact.company_id == c.id)) if e]
        last_mail = (
            db.scalar(select(func.max(MailMessage.received_at)).where(MailMessage.sender_email.in_(emails)))
            if emails
            else None
        )
        last = max([d.date() for d in (last_act, last_mail) if d], default=None)
        if last is None or last < since:
            out.append(
                {
                    "kind": "client_silencieux",
                    "title": f"Reprendre contact avec {c.name}",
                    "detail": f"Aucun échange depuis {'plus de 60 jours' if last is None else last.strftime('%d/%m/%Y')}.",
                    "link": f"/crm/societes/{c.id}",
                    "ask": f"Fais le point sur la relation avec {c.name} et propose une prochaine action.",
                }
            )

    opps = db.scalars(
        select(Opportunity)
        .where(Opportunity.stage.in_(OPEN_STAGES), Opportunity.expected_close < today)
        .limit(3)
    ).all()
    for o in opps:
        out.append(
            {
                "kind": "affaire_en_retard",
                "title": f"Mettre à jour l'affaire « {o.title} »",
                "detail": f"Signature prévue le {o.expected_close.strftime('%d/%m/%Y')}, toujours ouverte.",
                "link": "/crm/pipeline",
                "ask": f"Que faire pour faire avancer l'affaire « {o.title} » ?",
            }
        )

    late_tasks = db.scalar(
        select(func.count())
        .select_from(Task)
        .where(
            Task.done.is_(False),
            Task.due_date < today,
            (Task.assignee_email == user.email) | (Task.assignee_email == ""),
        )
    )
    if late_tasks:
        out.append(
            {
                "kind": "taches_retard",
                "title": f"{late_tasks} tâche(s) en retard",
                "detail": "Terminez-les ou replanifiez-les.",
                "link": "/crm/taches",
                "ask": "Aide-moi à replanifier mes tâches en retard par ordre de priorité.",
            }
        )

    if mgr:
        soon = db.scalars(
            select(Subscription).where(
                Subscription.active.is_(True),
                Subscription.renewal_date.is_not(None),
                Subscription.renewal_date <= today + timedelta(days=30),
            )
        ).all()
        for s in [s for s in soon if s.link_count == 0][:2]:
            out.append(
                {
                    "kind": "abonnement_a_verifier",
                    "title": f"Vérifier l'abonnement {s.name} avant son renouvellement",
                    "detail": f"Renouvellement le {s.renewal_date.strftime('%d/%m/%Y')} · aucune dépense rattachée.",
                    "link": "/abonnements",
                    "ask": f"L'abonnement {s.name} est-il encore utile ? Cherche les dépenses correspondantes.",
                }
            )
        docs = db.scalars(
            select(FileRecord).where(
                FileRecord.expires_on.is_not(None), FileRecord.expires_on <= today + timedelta(days=30)
            )
        ).all()
        if docs:
            out.append(
                {
                    "kind": "documents_expiration",
                    "title": f"{len(docs)} document(s) expirés ou bientôt expirés",
                    "detail": ", ".join(d.name for d in docs[:3]),
                    "link": "/documents",
                    "ask": "Quels documents sont expirés ou vont expirer, et que faut-il renouveler ?",
                }
            )
        # Temps facturable du mois sur des clients sans facture ce mois-ci.
        month = today.replace(day=1)
        hours = dict(
            db.execute(
                select(TimeEntry.company_id, func.sum(TimeEntry.hours))
                .where(
                    TimeEntry.billable.is_(True),
                    TimeEntry.work_date >= month,
                    TimeEntry.company_id.is_not(None),
                )
                .group_by(TimeEntry.company_id)
            ).all()
        )
        billed = set(
            db.scalars(
                select(BillingDoc.company_id).where(
                    BillingDoc.kind == "invoice", BillingDoc.issue_date >= month
                )
            )
        )
        unbilled = {cid: h for cid, h in hours.items() if cid not in billed and h >= 1}
        if unbilled:
            out.append(
                {
                    "kind": "temps_non_facture",
                    "title": f"{sum(unbilled.values()):g} h facturables sans facture ce mois-ci",
                    "detail": f"{len(unbilled)} client(s) concerné(s).",
                    "link": "/temps",
                    "ask": "Quel temps facturable de ce mois n'a pas encore été facturé, par client ?",
                }
            )
    return out


def facts(db: Session, user: User) -> dict:
    today = date.today()
    mails = db.scalars(select(MailMessage).order_by(MailMessage.received_at.desc()).limit(300)).all()
    tags = [outlook.display_tag(m) for m in mails]
    tasks_today = db.scalars(
        select(Task.title).where(
            Task.done.is_(False),
            Task.due_date <= today,
            (Task.assignee_email == user.email) | (Task.assignee_email == ""),
        )
    ).all()
    taxes = db.scalars(
        select(TaxDeadline).where(
            TaxDeadline.status == "todo", TaxDeadline.due_date <= today + timedelta(days=14)
        )
    ).all()
    out = {
        "date": today.isoformat(),
        "mails_a_repondre": tags.count("a_repondre"),
        "mails_urgents": tags.count("urgent"),
        "taches_du_jour_ou_en_retard": tasks_today[:8],
        "echeances_fiscales_14j": [
            {"titre": t.title, "date": t.due_date.isoformat(), "montant": t.amount} for t in taxes
        ],
    }
    if is_manager(user):
        invoices = db.scalars(
            select(BillingDoc).where(BillingDoc.kind == "invoice", BillingDoc.status == "sent")
        ).all()
        late = [d for d in invoices if billing.overdue(d)]
        out["factures_en_retard"] = {
            "nombre": len(late),
            "montant": round(sum(billing.remaining(d) for d in late), 2),
        }
        from app.services import treasury

        out["tresorerie"] = treasury.current_balance(db)
    # Les tâches et factures en retard figurent déjà dans les faits ci-dessus.
    out["suggestions"] = [
        s["title"] for s in suggestions(db, user) if s["kind"] not in ("taches_retard", "factures_retard")
    ]
    return out


def _fallback(f: dict) -> dict:
    points = []
    if f["mails_urgents"] or f["mails_a_repondre"]:
        points.append(
            f"{f['mails_a_repondre'] + f['mails_urgents']} mail(s) à traiter, dont {f['mails_urgents']} urgent(s)."
        )
    if f.get("factures_en_retard", {}).get("nombre"):
        fr = f["factures_en_retard"]
        points.append(f"{fr['nombre']} facture(s) en retard : {_money(fr['montant'])} à encaisser.")
    if f["taches_du_jour_ou_en_retard"]:
        points.append(f"{len(f['taches_du_jour_ou_en_retard'])} tâche(s) pour aujourd'hui ou en retard.")
    for t in f["echeances_fiscales_14j"][:2]:
        points.append(f"Échéance : {t['titre']} le {date.fromisoformat(t['date']).strftime('%d/%m')}.")
    points += f["suggestions"][: max(0, 5 - len(points))]
    return {
        "headline": "Rien d'urgent aujourd'hui." if not points else "Voici l'essentiel du jour.",
        "points": points[:5],
    }


def _write(db: Session, user: User, f: dict) -> tuple[dict, int, int]:
    """Rédaction par l'IA ; repli automatique sans IA (pas de clé, budget atteint, erreur)."""
    key = integrations.get(db, "anthropic_api_key")
    if not key or copilot.spent_this_month(db) >= copilot.budget(db):
        return _fallback(f), 0, 0
    try:
        client = anthropic.Anthropic(api_key=key, timeout=60, max_retries=1)
        r = client.beta.messages.create(
            model=copilot.MODEL,
            max_tokens=2000,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[
                {
                    "role": "user",
                    "content": PROMPT.format(
                        name=user.name or user.email, facts=json.dumps(f, ensure_ascii=False, default=str)
                    ),
                }
            ],
        )
        if r.stop_reason in ("refusal", "max_tokens"):
            return _fallback(f), 0, 0
        data = json.loads(next(b.text for b in r.content if b.type == "text"))
        data = {"headline": str(data["headline"])[:200], "points": [str(p)[:400] for p in data["points"]][:5]}
        return data, r.usage.input_tokens or 0, r.usage.output_tokens or 0
    except (anthropic.APIError, ValueError, KeyError, StopIteration):
        return _fallback(f), 0, 0


def get(db: Session, user: User, refresh: bool = False) -> dict:
    today = date.today()
    row = db.scalar(select(CopilotBrief).where(CopilotBrief.user_id == user.id, CopilotBrief.day == today))
    sugg = suggestions(db, user)  # toujours à jour (calcul local, gratuit)
    if row and not refresh:
        return json.loads(row.content) | {"suggestions": sugg, "generated_at": row.created_at}
    f = facts(db, user)
    data, tin, tout = _write(db, user, f)
    if row is None:
        row = CopilotBrief(user_id=user.id, day=today)
        db.add(row)
    data["ai"] = tout > 0
    row.content = json.dumps(data, ensure_ascii=False)
    row.input_tokens, row.output_tokens = (row.input_tokens or 0) + tin, (row.output_tokens or 0) + tout
    from app.core.db import utcnow

    row.created_at = utcnow()
    db.commit()
    return data | {"suggestions": sugg, "generated_at": row.created_at}
