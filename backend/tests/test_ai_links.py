import json
from datetime import date, timedelta

from app.models import BankAccount, Company, Contact, CopilotUsage, MailMessage, Subscription, Transaction
from app.services import integrations, links, mail_ai
from tests.llm_fake import FakeLLM


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


def test_ai_triage_summarizes_todo_mails(client, db, monkeypatch):
    todo = add_mail(db, "client@acme.fr", "Devis site")
    info = add_mail(db, "news@shop.fr", "Promo", tag="info")
    assert client.post("/api/mail/ai-triage").status_code == 400  # pas de clé

    integrations.put(db, "gemini_api_key", "AIza-test")
    assert [m.id for m in mail_ai.pending(db)] == [todo.id]  # seulement les mails à traiter
    fake = FakeLLM(
        monkeypatch,
        payload={
            "mails": [{"id": todo.id, "summary": "Demande un devis pour un site.", "intent": "demande_devis"}]
        },
    )
    assert mail_ai.analyze(db, mail_ai.pending(db)) == 1
    sent = json.loads(fake.calls[0]["contents"][0]["parts"][0]["text"].split("Mails :\n", 1)[1])
    assert [m["id"] for m in sent] == [todo.id]  # le mail « info » n'est pas envoyé à l'IA
    db.refresh(todo)
    db.refresh(info)
    assert todo.ai_intent == "demande_devis" and todo.ai_summary and info.ai_summary == ""
    assert db.query(CopilotUsage).count() == 1 and mail_ai.pending(db) == []
    out = {m["subject"]: m for m in client.get("/api/mail/messages").json()}
    assert out["Devis site"]["ai_intent"] == "demande_devis"


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
