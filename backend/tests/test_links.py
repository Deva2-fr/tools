from datetime import date, timedelta

from app.models import BankAccount, Company, Contact, MailMessage, Subscription, Transaction
from app.services import links


def add_mail(db, sender, subject="Demande", tag="a_repondre", **kw):
    m = MailMessage(
        graph_id=f"t:{sender}:{subject}",
        sender_email=sender,
        sender_name="X",
        subject=subject,
        preview="Pouvez-vous nous faire un devis ?",
        received_at=kw.pop("received_at", None) or __import__("app.core.db", fromlist=["utcnow"]).utcnow(),
        auto_tag=tag,
        **kw,
    )
    db.add(m)
    db.commit()
    return m


def test_mail_linked_to_contact_or_company_domain(client, db):
    acme = Company(name="Acme", kind="client", website="https://www.acme.fr")
    db.add(acme)
    db.flush()
    db.add(Contact(first_name="Bob", email="bob@partenaire.com", company_id=acme.id))
    db.commit()
    add_mail(db, "bob@partenaire.com", "Contact connu")
    add_mail(db, "marie@acme.fr", "Domaine connu")
    add_mail(db, "inconnu@gmail.com", "Messagerie publique")
    mails = {m["subject"]: m for m in client.get("/api/mail/messages").json()}
    assert mails["Contact connu"]["company_name"] == "Acme" and mails["Contact connu"]["contact_id"]
    assert mails["Domaine connu"]["company_id"] == acme.id and mails["Domaine connu"]["contact_id"] is None
    assert mails["Messagerie publique"]["company_id"] is None
    assert links.domain_of("https://www.Acme.fr/contact") == "acme.fr"


def test_debits_suggested_and_added_to_subscription(client, db):
    acc = BankAccount(name="Qonto", initial_balance=0)
    db.add(acc)
    db.flush()
    sub = Subscription(name="Hébergement", vendor="OVH", cost=10, period="monthly", active=True)
    db.add(sub)
    db.flush()
    t1 = Transaction(
        account_id=acc.id, tx_date=date.today() - timedelta(days=5), label="PRLV SEPA OVH SAS", amount=-12
    )
    t2 = Transaction(account_id=acc.id, tx_date=date.today(), label="Virement client", amount=500)
    db.add_all([t1, t2])
    db.commit()
    sugg = client.get("/api/subscriptions/link-suggestions").json()
    assert [(s["subscription_id"], s["transaction_id"]) for s in sugg] == [(sub.id, t1.id)]
    r = client.post(f"/api/subscriptions/{sub.id}/links/add", json={"transaction_ids": [t1.id]})
    assert r.status_code == 200, r.text
    assert client.get("/api/subscriptions/link-suggestions").json() == []
    assert (
        client.post(f"/api/subscriptions/{sub.id}/links/add", json={"transaction_ids": [t2.id]}).status_code
        == 400
    )
