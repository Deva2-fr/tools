import imaplib
from email.message import EmailMessage

import pytest
from sqlalchemy import select

from app.models import MailMessage
from app.services import integrations, mail_imap, mailbox


def make(msg_id, sender, subject, body, date="Mon, 26 Oct 2026 09:00:00 +0100", in_reply_to=None, html=False):
    m = EmailMessage()
    m["From"] = sender
    m["To"] = "contact@deva2.fr"
    m["Subject"] = subject
    m["Date"] = date
    m["Message-ID"] = msg_id
    if in_reply_to:
        m["In-Reply-To"] = in_reply_to
        m["References"] = in_reply_to
    if html:
        m.set_content(body, subtype="html")  # mail en HTML seulement
    else:
        m.set_content(body)
    return m.as_bytes()


class FakeImap:
    """Serveur IMAP en mémoire qui répond au format d'imaplib."""

    def __init__(self, inbox, sent, sent_name="Sent"):
        self.folders = {"INBOX": inbox, sent_name: sent}
        self.sent_name = sent_name
        self.current = None
        self.calls = []

    def list(self):
        return "OK", [
            b'(\\HasNoChildren) "/" "INBOX"',
            f'(\\HasNoChildren \\Sent) "/" "{self.sent_name}"'.encode(),
        ]

    def select(self, folder, readonly=False):
        self.calls.append(("select", folder, readonly))
        self.current = self.folders.get(folder.strip('"'))
        return ("OK", [str(len(self.current)).encode()]) if self.current is not None else ("NO", [b"no"])

    def uid(self, cmd, *args):
        self.calls.append(("uid", cmd, args))
        if cmd == "SEARCH":
            return "OK", [b" ".join(str(u).encode() for u in self.current)]
        uids = [int(u) for u in args[0].split(",")]
        what = args[1]
        data = []
        for u in uids:
            raw, flags = self.current[u]
            if what == "(UID FLAGS RFC822.SIZE)":
                data.append(f"{u} (UID {u} FLAGS ({' '.join(flags)}) RFC822.SIZE {len(raw)})".encode())
            else:
                body = raw if what == "(BODY.PEEK[])" else raw.split(b"\n\n")[0]
                data.append((f"{u} (UID {u} BODY[] {{{len(body)}}}".encode(), body))
                data.append(b")")
        return "OK", data

    def logout(self):
        return "BYE", []


INBOX = {
    1: (
        make("<a@client.fr>", "Bob Client <bob@client.fr>", "Devis site", "Pouvez-vous m'envoyer le devis ?"),
        ["\\Seen"],
    ),
    2: (
        make(
            "<b@client.fr>",
            "=?utf-8?q?C=C3=A9line?= <celine@client.fr>",
            "=?utf-8?q?Relance_urgente_=C3=A9t=C3=A9?=",
            "<p>Merci de me <b>répondre</b> ?</p>",
            html=True,
        ),
        [],
    ),
    3: (
        make("<c@client.fr>", "Ana <ana@client.fr>", "Question facture", "Avez-vous reçu le paiement ?"),
        ["\\Seen", "\\Answered"],
    ),
    4: (make("<d@github.com>", "GitHub <noreply@github.com>", "Notification", "Merci de confirmer ?"), []),
    5: (
        make("<e@client.fr>", "Eve <eve@client.fr>", "Rendez-vous", "Êtes-vous disponible jeudi ?"),
        ["\\Seen"],
    ),
}
SENT = {
    9: (
        make("<r@deva2.fr>", "contact@deva2.fr", "Re: Rendez-vous", "Oui", in_reply_to="<e@client.fr>"),
        ["\\Seen"],
    )
}


@pytest.fixture()
def imap_db(db):
    integrations.put(db, "imap_host", "mail.deva2.fr")
    integrations.put(db, "imap_user", "contact@deva2.fr")
    integrations.put(db, "imap_password", "pw")
    return db


def tags(db):
    from app.services.outlook import display_tag

    return {m.subject: display_tag(m) for m in db.scalars(select(MailMessage))}


def test_sync_tags_and_decoding(imap_db):
    fake = FakeImap(dict(INBOX), dict(SENT))
    assert mail_imap.sync_inbox(imap_db, conn=fake) == 5
    t = tags(imap_db)
    assert t["Devis site"] == "a_repondre"
    assert t["Relance urgente été"] == "urgent"  # sujet encodé décodé + mot « urgente »
    assert t["Question facture"] == "repondu"  # drapeau \Answered
    assert t["Rendez-vous"] == "repondu"  # réponse trouvée dans le dossier Envoyés
    assert t["Notification"] == "info"  # expéditeur automatique
    celine = imap_db.scalar(select(MailMessage).where(MailMessage.sender_email == "celine@client.fr"))
    assert celine.sender_name == "Céline" and celine.is_read is False
    assert "répondre" in celine.preview and "<b>" not in celine.preview  # HTML nettoyé


def test_read_only_and_no_duplicates(imap_db):
    fake = FakeImap(dict(INBOX), dict(SENT))
    mail_imap.sync_inbox(imap_db, conn=fake)
    assert mail_imap.sync_inbox(imap_db, conn=fake) == 0
    assert len(imap_db.scalars(select(MailMessage)).all()) == 5
    selects = [c for c in fake.calls if c[0] == "select"]
    assert selects and all(readonly for _, _, readonly in selects)  # dossiers ouverts en lecture seule
    fetches = [c[2][1] for c in fake.calls if c[0] == "uid" and c[1] == "FETCH"]
    assert all("BODY[]" not in f or "PEEK" in f for f in fetches)  # jamais de lecture qui marque « lu »
    assert not any(c[0] == "uid" and c[1] == "STORE" for c in fake.calls)


def test_sent_folder_detection():
    fake = FakeImap({}, {}, sent_name="Éléments envoyés")
    assert mail_imap.find_sent_folder(fake) == "Éléments envoyés"
    assert mail_imap.find_sent_folder(fake, "Mon dossier") == "Mon dossier"


def test_reply_closes_manual_todo(imap_db):
    inbox = {5: INBOX[5]}
    mail_imap.sync_inbox(imap_db, conn=FakeImap(inbox, {}))
    row = imap_db.scalar(select(MailMessage))
    row.manual_tag = "a_repondre"
    imap_db.commit()
    mail_imap.sync_inbox(imap_db, conn=FakeImap(inbox, dict(SENT)))
    imap_db.refresh(row)
    assert row.manual_tag == "fait"


def test_login_error_is_readable(imap_db, monkeypatch):
    class Refuse:
        def __init__(self, *a, **k):
            pass

        def login(self, *a):
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")

        def logout(self):
            pass

    monkeypatch.setattr(imaplib, "IMAP4_SSL", Refuse)
    with pytest.raises(mail_imap.ImapError, match="refuse"):
        mail_imap.connect(imap_db)


def test_provider_choice_and_endpoints(client, db, monkeypatch):
    assert client.get("/api/mail/status").json()["provider"] is None
    assert client.post("/api/mail/sync").status_code == 400
    integrations.put(db, "imap_host", "mail.deva2.fr")
    integrations.put(db, "imap_user", "contact@deva2.fr")
    integrations.put(db, "imap_password", "pw")
    integrations.put(db, "imap_webmail_url", "https://webmail.deva2.fr")
    assert mailbox.provider(db) == "imap"
    st = client.get("/api/mail/status").json()
    assert (
        st["connected"]
        and st["mailbox"] == "contact@deva2.fr"
        and st["webmail_url"] == "https://webmail.deva2.fr"
    )
    monkeypatch.setattr(mail_imap, "connect", lambda _db: FakeImap(dict(INBOX), dict(SENT)))
    assert client.post("/api/mail/sync").json() == {"new": 5}
    assert client.get("/api/mail/messages").json()[0]["web_link"] == "https://webmail.deva2.fr"
    assert "Connexion OK" in client.post("/api/integrations/test/imap").json()["message"]
    fields = {f["key"]: f for f in client.get("/api/integrations").json()}
    assert fields["imap_password"]["value"] == "" and fields["imap_password"]["is_set"]
