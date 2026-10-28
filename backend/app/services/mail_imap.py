"""Lecture d'une boîte mail classique en IMAP (serveur de l'hébergeur, pas Microsoft 365).

Strictement en lecture seule : dossiers ouverts en « readonly » et messages lus avec BODY.PEEK,
donc le Hub ne marque jamais un mail comme lu et ne déplace ni ne supprime rien.

Un mail est considéré « répondu » si le serveur porte le drapeau \\Answered (posé par Outlook,
Thunderbird… quand on répond) ou si un message du dossier « Envoyés » y fait référence
(In-Reply-To / References), ce qui couvre les réponses faites depuis un autre appareil.
"""

import email
import imaplib
import re
import ssl
from datetime import UTC, datetime, timedelta
from email.header import decode_header, make_header
from email.message import Message
from email.policy import default as default_policy
from email.utils import getaddresses, parsedate_to_datetime
from html import unescape

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import decrypt
from app.core.db import utcnow
from app.models import Mailbox, MailMessage
from app.services import outlook

DAYS = 30
MAX_MESSAGES = 300
MAX_BODY_SIZE = 2 * 1024 * 1024  # au-delà : en-têtes seulement (pas d'aperçu)
SENT_NAMES = (
    "Sent",
    "Sent Items",
    "Sent Messages",
    "INBOX.Sent",
    "INBOX/Sent",
    "Envoyés",
    "Éléments envoyés",
    "Elements envoyes",
    "Messages envoyés",
)
HEADER_FIELDS = "FROM SUBJECT DATE MESSAGE-ID IN-REPLY-TO REFERENCES"


class ImapError(RuntimeError):
    """Configuration manquante, identifiants refusés ou serveur injoignable (message affichable)."""


def connect(box: Mailbox) -> imaplib.IMAP4:
    host, user = box.host.strip(), box.username.strip()
    password = decrypt(box.password_enc) if box.password_enc else ""
    if not (host and user and password):
        raise ImapError(
            f"Boîte « {box.name} » incomplète : serveur, identifiant et mot de passe sont requis."
        )
    port = box.port or 993
    ctx = ssl.create_default_context()
    try:
        if port == 993:
            conn = imaplib.IMAP4_SSL(host, port, ssl_context=ctx, timeout=20)
        else:
            conn = imaplib.IMAP4(host, port, timeout=20)
            conn.starttls(ssl_context=ctx)  # obligatoire : jamais de mot de passe en clair
    except (TimeoutError, OSError, imaplib.IMAP4.error) as exc:
        raise ImapError(
            f"Serveur IMAP injoignable ({host}:{port}) : vérifiez le nom du serveur et le port."
        ) from exc
    try:
        conn.login(user, password)
    except imaplib.IMAP4.error as exc:
        _logout(conn)
        raise ImapError("Le serveur IMAP refuse l'identifiant ou le mot de passe.") from exc
    return conn


def _logout(conn) -> None:
    try:
        conn.logout()
    except Exception:  # noqa: BLE001 - on ferme au mieux
        pass


def _decode(value) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(str(value)))).strip()
    except Exception:  # noqa: BLE001 - en-tête mal encodé : on garde le brut
        return str(value).strip()


def _quote(folder: str) -> str:
    return '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'


def find_sent_folder(conn, configured: str = "") -> str | None:
    """Dossier « Envoyés » : réglage explicite, sinon attribut \\Sent, sinon noms usuels."""
    if configured:
        return configured
    typ, data = conn.list()
    if typ != "OK":
        return None
    folders: list[tuple[str, str]] = []
    for raw in data or []:
        line = raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)
        m = re.match(r'\((?P<flags>[^)]*)\)\s+(?:"[^"]*"|NIL)\s+(?P<name>.+)$', line)
        if not m:
            continue
        name = m.group("name").strip()
        if name.startswith('"') and name.endswith('"'):
            name = name[1:-1].replace('\\"', '"')
        folders.append((m.group("flags"), name))
    for flags, name in folders:
        if "\\Sent" in flags:
            return name
    by_lower = {name.lower(): name for _, name in folders}
    for candidate in SENT_NAMES:
        if candidate.lower() in by_lower:
            return by_lower[candidate.lower()]
    return None


def _uids_since(conn, days: int) -> list[bytes]:
    since = (datetime.now(UTC) - timedelta(days=days)).strftime("%d-%b-%Y")
    typ, data = conn.uid("SEARCH", None, "SINCE", since)
    if typ != "OK" or not data or not data[0]:
        return []
    return data[0].split()[-MAX_MESSAGES:]


def _fetch(conn, uids: list[bytes], what: str) -> list[tuple[bytes, bytes]]:
    """Renvoie [(ligne de métadonnées, contenu)] pour chaque message."""
    if not uids:
        return []
    typ, data = conn.uid("FETCH", b",".join(uids).decode(), what)
    if typ != "OK":
        return []
    return [(item[0], item[1]) for item in data or [] if isinstance(item, tuple) and len(item) == 2]


def _fetch_flags_sizes(conn, uids: list[bytes]) -> dict[bytes, tuple[set[str], int]]:
    """UID -> (drapeaux, taille). Ces réponses n'ont pas de contenu « littéral » : des lignes simples."""
    if not uids:
        return {}
    typ, data = conn.uid("FETCH", b",".join(uids).decode(), "(UID FLAGS RFC822.SIZE)")
    out: dict[bytes, tuple[set[str], int]] = {}
    for item in (data or []) if typ == "OK" else []:
        line = item[0] if isinstance(item, tuple) else item
        if not isinstance(line, bytes):
            continue
        uid = re.search(rb"UID (\d+)", line)
        size = re.search(rb"RFC822\.SIZE (\d+)", line)
        if uid:
            flags = {f.decode() for f in imaplib.ParseFlags(line)}
            out[uid.group(1)] = (flags, int(size.group(1)) if size else 0)
    return out


def _ids(value: str) -> set[str]:
    return set(re.findall(r"<[^<>\s]+>", value or ""))


def replied_ids(conn, sent_folder: str | None) -> set[str]:
    """Message-ID des mails auxquels on a répondu, d'après le dossier Envoyés."""
    if not sent_folder:
        return set()
    typ, _ = conn.select(_quote(sent_folder), readonly=True)
    if typ != "OK":
        return set()
    out: set[str] = set()
    for _meta, raw in _fetch(
        conn, _uids_since(conn, DAYS), "(BODY.PEEK[HEADER.FIELDS (IN-REPLY-TO REFERENCES)])"
    ):
        msg = email.message_from_bytes(raw)
        out |= _ids(msg.get("In-Reply-To", "")) | _ids(msg.get("References", ""))
    return out


def _text_preview(msg: Message) -> str:
    try:
        part = msg.get_body(preferencelist=("plain", "html"))  # type: ignore[attr-defined]
        if part is None:
            return ""
        text = part.get_content()
        if part.get_content_type() == "text/html":
            text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
            text = unescape(re.sub(r"<[^>]+>", " ", text))
    except Exception:  # noqa: BLE001 - corps illisible : pas d'aperçu
        return ""
    return re.sub(r"\s+", " ", text).strip()[:600]


def parse_message(raw: bytes, flags: set[str], uid: str = "?") -> dict:
    """Transforme un message IMAP (contenu + drapeaux) en champs du Hub."""
    msg = email.message_from_bytes(raw, policy=default_policy)
    name, addr = (getaddresses([str(msg.get("From", ""))]) or [("", "")])[0]
    try:
        received = parsedate_to_datetime(str(msg.get("Date"))).astimezone(UTC)
    except (TypeError, ValueError, IndexError):
        received = utcnow()
    message_id = (str(msg.get("Message-ID", "")).strip() or f"uid-{uid}")[:380]
    refs = _ids(str(msg.get("References", ""))) or _ids(str(msg.get("In-Reply-To", "")))
    return {
        "message_id": message_id,
        "thread": (sorted(refs)[0] if refs else message_id)[:400],
        "subject": _decode(msg.get("Subject", ""))[:500],
        "sender_name": _decode(name)[:255],
        "sender_email": (addr or "").lower()[:255],
        "received_at": received,
        "is_read": "\\Seen" in flags,
        "answered": "\\Answered" in flags,
        "preview": _text_preview(msg)
        if msg.is_multipart() or msg.get_content_type().startswith("text/")
        else "",
    }


def sync_inbox(db: Session, box: Mailbox, conn=None) -> int:
    """Synchronise les 30 derniers jours de la boîte de réception. Renvoie le nombre de nouveaux mails."""
    own = conn is None
    try:
        conn = conn or connect(box)
    except ImapError as exc:
        box.last_error = str(exc)[:300]
        db.commit()
        raise
    try:
        address = box.username.strip().lower()
        sent = replied_ids(conn, find_sent_folder(conn, box.sent_folder.strip()))
        typ, _ = conn.select("INBOX", readonly=True)
        if typ != "OK":
            raise ImapError("Impossible d'ouvrir la boîte de réception (INBOX).")
        uids = _uids_since(conn, DAYS)
        info = _fetch_flags_sizes(conn, uids)
        small = [u for u in uids if info.get(u, (set(), 0))[1] <= MAX_BODY_SIZE]
        big = [u for u in uids if info.get(u, (set(), 0))[1] > MAX_BODY_SIZE]
        items = _fetch(conn, small, "(BODY.PEEK[])")
        items += _fetch(conn, big, f"(BODY.PEEK[HEADER.FIELDS ({HEADER_FIELDS})])")

        created = 0
        for meta, raw in items:
            uid_m = re.search(rb"UID (\d+)", meta)
            uid = uid_m.group(1) if uid_m else b""
            p = parse_message(raw, info.get(uid, (set(), 0))[0], uid.decode() or "?")
            replied = p["answered"] or p["message_id"] in sent
            tag = outlook.classify(p["sender_email"], p["subject"], p["preview"], address, replied)
            # Clé propre à la boîte : un même mail reçu dans deux boîtes apparaît dans chacune.
            key = f"imap:{box.id}:{p['message_id']}"[:400]
            row = db.scalar(select(MailMessage).where(MailMessage.graph_id == key))
            if not row:
                row = MailMessage(graph_id=key, mailbox_id=box.id, received_at=p["received_at"])
                db.add(row)
                created += 1
            row.conversation_id = p["thread"]
            row.subject = p["subject"]
            row.sender_name = p["sender_name"]
            row.sender_email = p["sender_email"]
            row.preview = p["preview"]
            row.web_link = box.webmail_url.strip()
            row.is_read = p["is_read"]
            row.auto_tag = tag
            if replied and row.manual_tag in ("a_repondre", "urgent"):
                row.manual_tag = "fait"  # la réponse est partie : on referme automatiquement
        box.last_synced_at, box.last_error = utcnow(), ""
        db.commit()
        return created
    except ImapError as exc:
        db.rollback()
        box.last_error = str(exc)[:300]
        db.commit()
        raise
    finally:
        if own:
            _logout(conn)


def test_connection(box: Mailbox) -> str:
    conn = connect(box)
    try:
        typ, data = conn.select("INBOX", readonly=True)
        if typ != "OK":
            raise ImapError("Connexion OK mais la boîte de réception (INBOX) est introuvable.")
        count = (data[0] or b"0").decode() if data else "0"
        sent = find_sent_folder(conn, box.sent_folder.strip())
        sent_msg = (
            f"dossier des envoyés : « {sent} »"
            if sent
            else (
                "dossier des envoyés introuvable : précisez-le dans « Dossier des envoyés » pour mieux détecter les réponses"
            )
        )
        return f"Connexion OK – {count} message(s) dans la boîte de réception, {sent_msg}."
    finally:
        _logout(conn)
