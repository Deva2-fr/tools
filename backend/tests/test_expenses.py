import io
import json
from datetime import date

from PIL import Image
from pypdf import PdfReader
from reportlab.pdfgen import canvas


def png(color=(20, 20, 20, 255), size=(300, 100)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, "PNG")
    return buf.getvalue()


def pdf(pages=2) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for i in range(pages):
        c.drawString(100, 700, f"Ticket page {i + 1}")
        c.showPage()
    c.save()
    return buf.getvalue()


BODY = {"expense_date": str(date.today()), "reason": "Train Paris-Lyon", "amount_ttc": 120, "vat_rate": 10}


def save(c, body=None, files=None, expense_id=None, **form):
    url = "/api/expenses/save" + (f"?expense_id={expense_id}" if expense_id else "")
    return c.post(url, data={"data": json.dumps(body or BODY), **form}, files=files or [])


def pages(r) -> int:
    return len(PdfReader(io.BytesIO(r.content)).pages)


def sign(c, name="Sig", user_id=None):
    data = {"name": name} | ({"user_id": str(user_id)} if user_id else {})
    r = c.post("/api/expenses/signatures", data=data, files={"file": ("s.png", png(), "image/png")})
    assert r.status_code == 201, r.text
    return r.json()


def expense(c, eid):
    return next(x for x in c.get("/api/expenses").json() if x["id"] == eid)


def test_three_signatures_and_several_receipts(client, as_role):
    as_role("manager", "president@test.fr")
    as_role("manager", "associe@test.fr")
    people = {u["email"]: u for u in client.get("/api/users/directory").json()}
    me, pres, partner = people["admin@test.fr"], people["president@test.fr"], people["associe@test.fr"]
    s_me, s_pres, s_partner = (
        sign(client, "Moi"),
        sign(client, "Pdt", pres["id"]),
        sign(client, "Ass", partner["id"]),
    )
    img = client.get(f"/api/expenses/signatures/{s_me['id']}/image")
    assert img.headers["content-type"] == "image/png" and img.content.startswith(b"\x89PNG")

    body = {
        **BODY,
        "signature_id": s_me["id"],
        "president_signature_id": s_pres["id"],
        "partner_signature_id": s_partner["id"],
    }
    # Président et associé pas encore désignés : refusé
    assert save(client, body).status_code == 400
    r = client.put("/api/expenses/signers", json={"president": pres["id"], "partner": partner["id"]})
    assert r.json()["president"]["name"] == "president@test.fr"
    # Mauvaise personne dans la mauvaise case : refusé
    assert save(client, {**body, "president_signature_id": s_partner["id"]}).status_code == 400

    # Trois signatures + deux justificatifs (photo + PDF de 2 pages) : 1 + 1 + 2 pages
    files = [
        ("receipts", ("ticket.jpg", _jpg(), "image/jpeg")),
        ("receipts", ("facture.pdf", pdf(2), "application/pdf")),
    ]
    r = save(client, body, files=files)
    assert r.status_code == 200, r.text
    assert pages(r) == 4
    eid = int(r.headers["x-expense-id"])
    e = expense(client, eid)
    assert [f["name"] for f in e["receipt_files"]] == ["ticket.jpg", "facture.pdf"]
    assert e["president_signature_id"] == s_pres["id"] and e["user_id"] == me["id"]
    first, second = e["receipt_files"]
    assert client.get(f"/api/expenses/{eid}/receipts/{first['id']}").content.startswith(b"\xff\xd8\xff")

    # Ajout d'un troisième, retrait du premier : facture.pdf (2) + nouveau (1) = 1 + 3 pages
    r = save(
        client,
        body,
        files=[("receipts", ("taxi.png", png(), "image/png"))],
        expense_id=eid,
        remove_receipt_ids=[str(first["id"])],
    )
    assert r.status_code == 200 and pages(r) == 4
    assert [f["name"] for f in expense(client, eid)["receipt_files"]] == ["facture.pdf", "taxi.png"]
    assert client.get(f"/api/expenses/{eid}/receipts/{first['id']}").status_code == 404

    # Fichiers refusés ; un PDF corrompu n'enlève pas les justificatifs existants
    assert (
        save(
            client, body, files=[("receipts", ("x.exe", b"MZ", "application/octet-stream"))], expense_id=eid
        ).status_code
        == 400
    )
    assert (
        save(
            client, body, files=[("receipts", ("x.pdf", b"GIF89a", "application/pdf"))], expense_id=eid
        ).status_code
        == 400
    )
    bad = save(
        client,
        body,
        files=[("receipts", ("abime.pdf", b"%PDF-1.4 garbage", "application/pdf"))],
        expense_id=eid,
    )
    assert bad.status_code == 400 and "abime.pdf" in bad.json()["detail"]
    assert len(expense(client, eid)["receipt_files"]) == 2
    too_many = [("receipts", (f"t{i}.png", png(), "image/png")) for i in range(9)]
    assert save(client, body, files=too_many, expense_id=eid).status_code == 400

    # Signature : images non valides refusées
    assert (
        client.post(
            "/api/expenses/signatures", data={"name": "x"}, files={"file": ("s.png", b"nope", "image/png")}
        ).status_code
        == 400
    )


def test_president_signs_from_own_account(client, as_role):
    president = as_role("member", "pdt@test.fr")
    alice = as_role("member", "alice@test.fr")
    people = {u["email"]: u for u in client.get("/api/users/directory").json()}
    client.put("/api/expenses/signers", json={"president": people["pdt@test.fr"]["id"]})
    eid = int(save(alice).headers["x-expense-id"])
    # Le président (simple membre) voit la note d'Alice et y appose sa propre signature
    assert eid in [x["id"] for x in president.get("/api/expenses").json()]
    s = sign(president, "Pdt")
    e = expense(president, eid)
    body = {
        k: e[k] for k in ("expense_date", "reason", "amount_ttc", "vat_rate", "user_id", "signature_id")
    } | {"president_signature_id": s["id"]}
    assert save(president, body, expense_id=eid).status_code == 200
    assert expense(alice, eid)["president_signature_id"] == s["id"]
    # … mais Alice ne peut pas signer à la place du président
    assert alice.get(f"/api/expenses/signatures/{s['id']}/image").status_code == 400


def _jpg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (400, 600), (240, 240, 240)).save(buf, "JPEG")
    return buf.getvalue()


def test_users_and_permissions(client, as_role):
    member = as_role("member", "alice@test.fr")
    other = as_role("member", "bob@test.fr")
    users = {u["email"]: u for u in member.get("/api/users/directory").json()}
    alice, bob = users["alice@test.fr"], users["bob@test.fr"]

    # Un membre saisit pour lui-même, pas pour un autre
    assert save(member, {**BODY, "user_id": bob["id"]}).status_code == 403
    r = save(member)
    assert r.status_code == 200
    eid = int(r.headers["x-expense-id"])
    assert [x["id"] for x in member.get("/api/expenses").json()] == [eid]
    assert other.get("/api/expenses").json() == []  # Bob ne voit pas la note d'Alice
    assert other.get(f"/api/expenses/{eid}/pdf").status_code == 404
    assert other.delete(f"/api/expenses/{eid}").status_code == 404

    # Signatures personnelles
    s_alice = member.post(
        "/api/expenses/signatures", data={"name": "Alice"}, files={"file": ("a.png", png(), "image/png")}
    ).json()
    assert other.get("/api/expenses/signatures").json() == []
    assert save(other, {**BODY, "signature_id": s_alice["id"]}).status_code == 400
    assert (
        member.post(
            "/api/expenses/signatures",
            data={"name": "x", "user_id": bob["id"]},
            files={"file": ("a.png", png(), "image/png")},
        ).status_code
        == 403
    )

    # Un manager (admin) saisit pour Alice avec la signature d'Alice, et voit toutes les notes
    r = save(client, {**BODY, "user_id": alice["id"], "signature_id": s_alice["id"]})
    assert r.status_code == 200
    e = next(x for x in client.get("/api/expenses").json() if x["id"] == int(r.headers["x-expense-id"]))
    assert e["user_id"] == alice["id"] and e["employee"] == "alice@test.fr"
    # … mais pas avec la signature d'Alice sur une note de Bob
    assert save(client, {**BODY, "user_id": bob["id"], "signature_id": s_alice["id"]}).status_code == 400
    assert len(client.get(f"/api/expenses/signatures?user_id={alice['id']}").json()) == 1

    # Abonnement rattaché à un utilisateur
    sub = client.post("/api/subscriptions", json={"name": "Licence Figma", "user_id": alice["id"]})
    assert sub.status_code == 201 and sub.json()["user_id"] == alice["id"]


def test_user_profile_summary(client, as_role):
    alice = as_role("member", "alice@test.fr")
    as_role("member", "bob@test.fr")
    people = {u["email"]: u for u in client.get("/api/users/directory").json()}
    a_id = people["alice@test.fr"]["id"]
    save(alice, files=[("receipts", ("t.png", png(), "image/png"))])
    save(alice, {**BODY, "amount_ttc": 30})
    client.post(
        "/api/subscriptions", json={"name": "Figma", "user_id": a_id, "cost": 15, "period": "monthly"}
    )
    client.post("/api/subscriptions", json={"name": "Ancien", "user_id": a_id, "cost": 99, "active": False})
    sign(alice, "Alice")

    s = alice.get(f"/api/users/{a_id}/summary").json()
    assert s["user"]["email"] == "alice@test.fr"
    assert (
        s["expenses"]["count"] == 2
        and s["expenses"]["year_total"] == 150.0
        and s["expenses"]["without_receipt"] == 1
    )
    assert (
        s["subscriptions"]["count"] == 2
        and s["subscriptions"]["active"] == 1
        and s["subscriptions"]["annual_cost"] == 180.0
    )
    assert s["signatures"] == 1
    # Un autre membre ne voit pas le profil d'Alice ; un manager si
    bob = as_role("member", "bob@test.fr")
    assert bob.get(f"/api/users/{a_id}/summary").status_code == 403
    assert client.get(f"/api/users/{a_id}/summary").status_code == 200


def test_delete_signature(client, as_role):
    alice = as_role("member", "alice@test.fr")
    bob = as_role("member", "bob@test.fr")
    s = sign(alice, "Alice")
    eid = int(save(alice, {**BODY, "signature_id": s["id"]}).headers["x-expense-id"])
    assert bob.delete(f"/api/expenses/signatures/{s['id']}").status_code == 400  # pas la sienne
    assert alice.delete(f"/api/expenses/signatures/{s['id']}").status_code == 204
    assert alice.get("/api/expenses/signatures").json() == []
    assert expense(alice, eid)["signature_id"] is None  # retirée de la note
    # Un manager peut supprimer la signature de quelqu'un d'autre
    s2 = sign(alice, "Alice 2")
    assert client.delete(f"/api/expenses/signatures/{s2['id']}").status_code == 204
