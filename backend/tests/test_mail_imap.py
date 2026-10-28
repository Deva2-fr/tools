import imaplib
from datetime import UTC, datetime
from email.message import EmailMessage

import pytest
from sqlalchemy import select

from app.core.crypto import encrypt
from app.models import Mailbox, MailMessage
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
        self.validity = b"1"

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
            if args[1:3] == ("HEADER", "Message-ID"):
                wanted = args[3].strip('"').encode()
                hits = [u for u, (raw, _) in self.current.items() if b"Message-ID: " + wanted in raw]
                return "OK", [b" ".join(str(u).encode() for u in hits)]
            return "OK", [b" ".join(str(u).encode() for u in self.current)]
        uids = [int(u) for u in args[0].split(",")]
        what = args[1]
        data = []
        for u in uids:
            if u not in self.current:  # comme un vrai serveur : UID inconnu ignoré
                continue
            raw, flags = self.current[u]
            if what == "(UID FLAGS RFC822.SIZE)":
                data.append(f"{u} (UID {u} FLAGS ({' '.join(flags)}) RFC822.SIZE {len(raw)})".encode())
            else:
                body = raw if what == "(BODY.PEEK[])" else raw.split(b"\n\n")[0]
                data.append((f"{u} (UID {u} BODY[] {{{len(body)}}}".encode(), body))
                data.append(b")")
        return "OK", data

    def response(self, code):
        return (code, [self.validity]) if code == "UIDVALIDITY" else (code, [None])

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


def add_box(db, name="Contact", user="contact@deva2.fr", webmail=""):
    box = Mailbox(
        name=name, host="mail.deva2.fr", username=user, password_enc=encrypt("pw"), webmail_url=webmail
    )
    db.add(box)
    db.commit()
    return box


@pytest.fixture()
def imap_db(db):
    db.box = add_box(db)
    return db


def tags(db):
    from app.services.outlook import display_tag

    return {m.subject: display_tag(m) for m in db.scalars(select(MailMessage))}


def test_sync_tags_and_decoding(imap_db):
    fake = FakeImap(dict(INBOX), dict(SENT))
    assert mail_imap.sync_inbox(imap_db, imap_db.box, conn=fake) == 5
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
    mail_imap.sync_inbox(imap_db, imap_db.box, conn=fake)
    assert mail_imap.sync_inbox(imap_db, imap_db.box, conn=fake) == 0
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
    mail_imap.sync_inbox(imap_db, imap_db.box, conn=FakeImap(inbox, {}))
    row = imap_db.scalar(select(MailMessage))
    row.manual_tag = "a_repondre"
    imap_db.commit()
    mail_imap.sync_inbox(imap_db, imap_db.box, conn=FakeImap(inbox, dict(SENT)))
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
        mail_imap.connect(imap_db.box)


def test_legacy_single_mailbox_is_migrated(db):
    integrations.put(db, "imap_host", "mail.deva2.fr")
    integrations.put(db, "imap_user", "contact@deva2.fr")
    integrations.put(db, "imap_password", "mot-de-passe-imap")
    integrations.put(db, "imap_webmail_url", "https://webmail.deva2.fr")
    db.add(MailMessage(graph_id="imap:<old@x>", subject="Ancien", received_at=mail_imap.utcnow()))
    db.commit()
    mailbox.migrate_legacy(db)
    (box,) = mailbox.boxes(db)
    assert (
        box.name == "Contact" and box.username == "contact@deva2.fr" and box.webmail_url.endswith("deva2.fr")
    )
    assert box.password_enc and "mot-de-passe-imap" not in box.password_enc  # chiffré
    old = db.scalar(select(MailMessage).where(MailMessage.subject == "Ancien"))
    assert old.mailbox_id == box.id and old.graph_id == f"imap:{box.id}:<old@x>"
    assert integrations.get(db, "imap_host") == ""  # anciens réglages vidés
    mailbox.migrate_legacy(db)  # idempotent
    assert len(mailbox.boxes(db)) == 1


def test_several_mailboxes_and_endpoints(client, db, as_role, monkeypatch):
    assert client.get("/api/mail/status").json()["connected"] is False
    assert client.post("/api/mail/sync").status_code == 400

    body = {
        "name": "Contact",
        "host": "mail.deva2.fr",
        "username": "contact@deva2.fr",
        "password": "pw",
        "webmail_url": "https://webmail.deva2.fr",
    }
    contact = client.post("/api/mail/mailboxes", json=body).json()
    assert "password" not in contact and contact["has_password"]
    assert client.post("/api/mail/mailboxes", json={**body, "password": ""}).status_code == 400
    compta = client.post(
        "/api/mail/mailboxes", json={**body, "name": "Compta", "username": "compta@deva2.fr", "position": 1}
    ).json()
    assert as_role("member").post("/api/mail/mailboxes", json=body).status_code == 403
    assert as_role("member").get("/api/mail/status").status_code == 200

    # Contact : 5 mails (3 à traiter) ; Compta : 1 mail, et le même mail « Devis » reçu dans les deux boîtes.
    def fake_connect(box):
        if box.username.startswith("compta"):
            return FakeImap({1: INBOX[1]}, {})
        return FakeImap(dict(INBOX), dict(SENT))

    monkeypatch.setattr(mail_imap, "connect", fake_connect)
    assert client.post("/api/mail/sync").json() == {"new": 6, "errors": []}
    assert client.post(f"/api/mail/sync?mailbox_id={compta['id']}").json()["new"] == 0
    st = client.get("/api/mail/status").json()
    assert [b["name"] for b in st["mailboxes"]] == ["Contact", "Compta"]
    assert [b["todo"] for b in st["mailboxes"]] == [2, 1]
    assert len(client.get("/api/mail/messages").json()) == 6
    only = client.get(f"/api/mail/messages?mailbox={compta['id']}").json()
    assert len(only) == 1 and only[0]["mailbox_id"] == compta["id"] and only[0]["subject"] == "Devis site"
    assert client.get("/api/mail/messages?mailbox=microsoft").json() == []
    assert (
        client.post(f"/api/mail/mailboxes/{contact['id']}/test").json()["message"].startswith("Connexion OK")
    )

    # Modification sans mot de passe = mot de passe conservé ; désactivation = bouton masqué.
    r = client.put(
        f"/api/mail/mailboxes/{compta['id']}",
        json={**body, "name": "Compta", "password": "", "active": False},
    )
    assert r.status_code == 200 and r.json()["has_password"]
    assert [b["name"] for b in client.get("/api/mail/status").json()["mailboxes"]] == ["Contact"]

    # Une boîte en erreur n'empêche pas les autres d'être relues.
    def broken(box):
        raise mail_imap.ImapError("Le serveur IMAP refuse l'identifiant ou le mot de passe.")

    client.put(f"/api/mail/mailboxes/{compta['id']}", json={**body, "name": "Compta", "active": True})
    monkeypatch.setattr(
        mail_imap, "connect", lambda box: broken(box) if box.name == "Compta" else fake_connect(box)
    )
    res = client.post("/api/mail/sync").json()
    assert res["errors"] and "Compta" in res["errors"][0]
    assert client.get("/api/mail/mailboxes").json()[1]["last_error"].startswith("Le serveur IMAP refuse")
    assert client.post(f"/api/mail/sync?mailbox_id={compta['id']}").status_code == 400

    # Supprimer une boîte supprime ses mails dans le Hub (rien sur le serveur).
    assert client.delete(f"/api/mail/mailboxes/{compta['id']}").status_code == 204
    assert len(client.get("/api/mail/messages").json()) == 5


def body_fetches(fake):
    return [c for c in fake.calls if c[0] == "uid" and c[1] == "FETCH" and c[2][1] == "(BODY.PEEK[])"]


def test_incremental_sync_whole_inbox(imap_db, monkeypatch):
    monkeypatch.setattr(mail_imap, "NEW_PER_SYNC", 3)
    inbox = dict(INBOX)
    fake = FakeImap(inbox, dict(SENT))
    assert mail_imap.sync_inbox(imap_db, imap_db.box, conn=fake) == 3  # les 3 plus récents d'abord
    assert {m.imap_uid for m in imap_db.scalars(select(MailMessage))} == {3, 4, 5}
    assert mail_imap.sync_inbox(imap_db, imap_db.box, conn=fake) == 2  # puis le reste
    fake.calls.clear()
    assert mail_imap.sync_inbox(imap_db, imap_db.box, conn=fake) == 0
    assert body_fetches(fake) == []  # rien n'est retéléchargé

    # Drapeau « répondu » posé plus tard par Outlook : le tag suit sans retélécharger le mail.
    inbox[1] = (inbox[1][0], ["\\Seen", "\\Answered"])
    mail_imap.sync_inbox(imap_db, imap_db.box, conn=fake)
    assert tags(imap_db)["Devis site"] == "repondu"

    # Mail supprimé / déplacé sur le serveur : il disparaît du Hub.
    del inbox[4]
    mail_imap.sync_inbox(imap_db, imap_db.box, conn=fake)
    assert "Notification" not in tags(imap_db) and len(tags(imap_db)) == 4

    # Numérotation réinitialisée par le serveur : resynchronisation propre, sans doublon.
    fake.validity = b"2"
    assert mail_imap.sync_inbox(imap_db, imap_db.box, conn=fake) == 0
    assert imap_db.box.uid_validity == "2" and len(imap_db.scalars(select(MailMessage)).all()) == 4


def test_messages_filters_search_and_paging(client, db, monkeypatch):
    box = add_box(db)
    mail_imap.sync_inbox(db, box, conn=FakeImap(dict(INBOX), dict(SENT)))
    r = client.get("/api/mail/messages")
    assert r.status_code == 200 and len(r.json()) == 5 and r.headers["x-total-count"] == "5"
    assert dict(x.split("=") for x in r.headers["x-counts"].split(",")) == {
        "todo": "2",
        "repondu": "2",
        "info": "1",
        "all": "5",
    }
    todo = client.get("/api/mail/messages?filter=todo").json()
    assert {m["subject"] for m in todo} == {"Devis site", "Relance urgente été"}
    assert [m["subject"] for m in client.get("/api/mail/messages?q=facture").json()] == ["Question facture"]
    assert [m["sender_email"] for m in client.get("/api/mail/messages?q=celine").json()] == [
        "celine@client.fr"
    ]
    page2 = client.get("/api/mail/messages?limit=2&offset=4")
    assert len(page2.json()) == 1 and page2.headers["x-total-count"] == "5"


def test_read_full_mail_and_attachment(client, db, monkeypatch):
    from email.message import EmailMessage

    m = EmailMessage()
    m["From"] = "Bob Client <bob@client.fr>"
    m["To"] = "contact@deva2.fr"
    m["Cc"] = "Ana <ana@client.fr>"
    m["Subject"] = "Devis complet"
    m["Date"] = "Mon, 26 Oct 2026 09:00:00 +0100"
    m["Message-ID"] = "<full@client.fr>"
    m.set_content("Bonjour,\n\nVoici le cahier des charges complet.\n\n" + "Ligne détaillée.\n" * 200)
    m.add_alternative(
        "<p>Bonjour,</p><p>Voici le <b>cahier des charges</b>.</p><script>alert(1)</script>", subtype="html"
    )
    m.add_attachment(
        b"%PDF-1.4 cahier", maintype="application", subtype="pdf", filename="cahier des charges.pdf"
    )
    inbox = {7: (m.as_bytes(), ["\\Seen"])}
    box = add_box(db)
    fake = FakeImap(inbox, {})
    mail_imap.sync_inbox(db, box, conn=fake)
    monkeypatch.setattr(mail_imap, "connect", lambda _box: FakeImap(inbox, {}))
    mid = client.get("/api/mail/messages").json()[0]["id"]

    r = client.get(f"/api/mail/messages/{mid}/content")
    assert r.status_code == 200, r.text
    c = r.json()
    assert (
        c["subject"] == "Devis complet"
        and c["from"] == ["Bob Client <bob@client.fr>"]
        and c["cc"] == ["Ana <ana@client.fr>"]
    )
    assert c["text"].count("Ligne détaillée.") == 200  # le texte entier, pas un aperçu
    assert "<b>cahier des charges</b>" in c["html"]
    (att,) = c["attachments"]
    assert att["name"] == "cahier des charges.pdf" and att["type"] == "application/pdf"
    dl = client.get(f"/api/mail/messages/{mid}/attachments/{att['index']}")
    assert dl.content == b"%PDF-1.4 cahier" and dl.headers["content-type"] == "application/octet-stream"
    assert "attachment" in dl.headers["content-disposition"]

    # Mail disparu du serveur : message clair
    monkeypatch.setattr(mail_imap, "connect", lambda _box: FakeImap({}, {}))
    gone = client.get(f"/api/mail/messages/{mid}/content")
    assert gone.status_code == 400 and "plus sur le serveur" in gone.json()["detail"]


def test_read_mail_without_or_with_stale_uid(client, db, monkeypatch):
    """Mail importé avant le suivi des numéros IMAP (ou numéro périmé) : retrouvé par son Message-ID."""
    box = add_box(db)
    inbox = dict(INBOX)
    mail_imap.sync_inbox(db, box, conn=FakeImap(inbox, dict(SENT)))
    monkeypatch.setattr(mail_imap, "connect", lambda _box: FakeImap(inbox, dict(SENT)))
    row = db.scalar(select(MailMessage).where(MailMessage.subject == "Question facture"))
    for stale in (None, 99):
        row.imap_uid = stale
        db.commit()
        r = client.get(f"/api/mail/messages/{row.id}/content")
        assert r.status_code == 200, r.text
        assert "paiement" in r.json()["text"]
        db.refresh(row)
        assert row.imap_uid == 3  # numéro retrouvé et mémorisé


def test_sync_purges_rows_no_longer_in_inbox(imap_db):
    fake = FakeImap(dict(INBOX), dict(SENT))
    mail_imap.sync_inbox(imap_db, imap_db.box, conn=fake)
    # Ligne importée autrefois, sans numéro, dont le mail a quitté la boîte de réception.
    imap_db.add(
        MailMessage(
            graph_id=f"imap:{imap_db.box.id}:<old@client.fr>",
            mailbox_id=imap_db.box.id,
            subject="Ancien",
            received_at=datetime(2025, 1, 1, tzinfo=UTC),
        )
    )
    imap_db.commit()
    mail_imap.sync_inbox(imap_db, imap_db.box, conn=fake)
    assert "Ancien" not in tags(imap_db) and len(tags(imap_db)) == 5
