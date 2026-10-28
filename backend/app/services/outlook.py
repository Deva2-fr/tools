"""Lecture de la boîte Outlook via Microsoft Graph (OAuth2, lecture seule) + détection des mails à traiter."""

import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import utcnow
from app.models import MailMessage
from app.services import integrations

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = "offline_access User.Read Mail.Read"
AUTOMATED = re.compile(
    r"(no-?reply|noreply|do-?not-?reply|newsletter|notification|mailer-daemon|bounce|donotreply)", re.I
)
ASK_WORDS = re.compile(
    r"(\?|merci de|pouvez-vous|pourriez-vous|peux-tu|pourrais-tu|veuillez|relance|rappel|devis|facture|"
    r"disponibilit|rendez-vous|retour de votre part|dans l'attente|please|could you|can you|asap)",
    re.I,
)
URGENT_WORDS = re.compile(r"(urgent|urgence|asap|dernier rappel|mise en demeure|impay)", re.I)


def redirect_uri() -> str:
    return get_settings().base_url.rstrip("/") + "/api/mail/callback"


def authorize_url(db: Session, state: str) -> str:
    tenant = integrations.get(db, "microsoft_tenant_id", "common")
    q = urlencode(
        {
            "client_id": integrations.get(db, "microsoft_client_id"),
            "response_type": "code",
            "redirect_uri": redirect_uri(),
            "response_mode": "query",
            "scope": SCOPES,
            "state": state,
            "prompt": "select_account",
        }
    )
    return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?{q}"


def _token_request(db: Session, data: dict) -> dict:
    tenant = integrations.get(db, "microsoft_tenant_id", "common")
    body = {
        "client_id": integrations.get(db, "microsoft_client_id"),
        "client_secret": integrations.get(db, "microsoft_client_secret"),
        "scope": SCOPES,
        **data,
    }
    r = httpx.post(f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token", data=body, timeout=20)
    if r.status_code >= 400:
        raise RuntimeError(
            f"Microsoft a refusé la connexion : {r.json().get('error_description', r.text)[:200]}"
        )
    return r.json()


def exchange_code(db: Session, code: str) -> str:
    tok = _token_request(
        db, {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri()}
    )
    integrations.put(db, "microsoft_refresh_token", tok["refresh_token"])
    me = httpx.get(
        f"{GRAPH}/me", headers={"Authorization": f"Bearer {tok['access_token']}"}, timeout=20
    ).json()
    mailbox = me.get("mail") or me.get("userPrincipalName", "")
    integrations.put(db, "microsoft_mailbox", mailbox)
    return mailbox


def access_token(db: Session) -> str:
    refresh = integrations.get(db, "microsoft_refresh_token")
    if not refresh:
        raise RuntimeError("Boîte Outlook non connectée")
    tok = _token_request(db, {"grant_type": "refresh_token", "refresh_token": refresh})
    if tok.get("refresh_token"):
        integrations.put(db, "microsoft_refresh_token", tok["refresh_token"])
    return tok["access_token"]


def _get_all(client: httpx.Client, url: str, params: dict, limit: int = 300) -> list[dict]:
    items: list[dict] = []
    while url and len(items) < limit:
        r = client.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        items += data.get("value", [])
        url, params = data.get("@odata.nextLink"), None
    return items


def classify(sender_email: str, subject: str, preview: str, mailbox: str, replied: bool) -> str:
    """Retourne a_repondre | repondu | info."""
    if replied:
        return "repondu"
    if sender_email.lower() == mailbox.lower() or AUTOMATED.search(sender_email):
        return "info"
    if ASK_WORDS.search(f"{subject} {preview}"):
        return "a_repondre"
    return "info"


def is_urgent(subject: str, preview: str) -> bool:
    return bool(URGENT_WORDS.search(f"{subject} {preview}"))


def sync_inbox(db: Session, days: int = 30) -> int:
    token = access_token(db)
    mailbox = integrations.get(db, "microsoft_mailbox")
    since = (utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(headers=headers, timeout=30) as client:
        inbox = _get_all(
            client,
            f"{GRAPH}/me/mailFolders/inbox/messages",
            {
                "$filter": f"receivedDateTime ge {since}",
                "$orderby": "receivedDateTime desc",
                "$top": 50,
                "$select": "id,conversationId,subject,from,bodyPreview,receivedDateTime,isRead,webLink",
            },
        )
        sent = _get_all(
            client,
            f"{GRAPH}/me/mailFolders/sentitems/messages",
            {"$filter": f"sentDateTime ge {since}", "$top": 50, "$select": "conversationId,sentDateTime"},
        )
    last_sent: dict[str, datetime] = {}
    for m in sent:
        ts = datetime.fromisoformat(m["sentDateTime"].replace("Z", "+00:00"))
        last_sent[m["conversationId"]] = max(ts, last_sent.get(m["conversationId"], ts))

    count = 0
    for m in inbox:
        received = datetime.fromisoformat(m["receivedDateTime"].replace("Z", "+00:00")).astimezone(UTC)
        sender = m.get("from", {}).get("emailAddress", {})
        replied = m["conversationId"] in last_sent and last_sent[m["conversationId"]] > received
        tag = classify(
            sender.get("address", ""), m.get("subject", ""), m.get("bodyPreview", ""), mailbox, replied
        )
        row = db.scalar(select(MailMessage).where(MailMessage.graph_id == m["id"]))
        if not row:
            row = MailMessage(graph_id=m["id"], received_at=received)
            db.add(row)
            count += 1
        row.conversation_id = m["conversationId"]
        row.subject = m.get("subject", "")[:500]
        row.sender_name = sender.get("name", "")[:255]
        row.sender_email = sender.get("address", "")[:255]
        row.preview = m.get("bodyPreview", "")[:600]
        row.web_link = m.get("webLink", "")
        row.is_read = m.get("isRead", False)
        row.auto_tag = tag
        if replied and row.manual_tag in ("a_repondre", "urgent"):
            row.manual_tag = "fait"  # la réponse est partie : on referme automatiquement
    db.commit()
    return count


def display_tag(msg: MailMessage) -> str:
    """Tag affiché : le choix manuel prime sur la détection automatique."""
    if msg.manual_tag:
        return msg.manual_tag
    if msg.auto_tag == "a_repondre" and is_urgent(msg.subject, msg.preview):
        return "urgent"
    return msg.auto_tag


def message_content(db: Session, graph_id: str) -> dict:
    """Contenu complet d'un mail Microsoft 365 (même forme que mail_imap.full_content, sans pièces jointes)."""
    headers = {"Authorization": f"Bearer {access_token(db)}"}
    r = httpx.get(
        f"{GRAPH}/me/messages/{graph_id}",
        params={"$select": "subject,body,from,toRecipients,ccRecipients,receivedDateTime"},
        headers=headers,
        timeout=20,
    )
    r.raise_for_status()
    m = r.json()

    def addr(x: dict) -> str:
        e = x.get("emailAddress", {})
        return f"{e.get('name')} <{e.get('address')}>" if e.get("name") else e.get("address", "")

    body = m.get("body") or {}
    html = body.get("content", "") if body.get("contentType") == "html" else ""
    return {
        "subject": m.get("subject", ""),
        "from": [addr(m["from"])] if m.get("from") else [],
        "to": [addr(x) for x in m.get("toRecipients", [])],
        "cc": [addr(x) for x in m.get("ccRecipients", [])],
        "date": m.get("receivedDateTime", ""),
        "text": "" if html else body.get("content", ""),
        "html": html,
        "attachments": [],
    }
