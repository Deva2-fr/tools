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
    return c.post(url, data={"data": json.dumps(body or BODY), **form}, files=files)


def pages(r) -> int:
    return len(PdfReader(io.BytesIO(r.content)).pages)


def test_signature_and_receipts_in_pdf(client, tmp_path):
    me = next(u for u in client.get("/api/users/directory").json() if u["email"] == "admin@test.fr")
    sig = client.post(
        "/api/expenses/signatures",
        data={"name": "Ma signature"},
        files={"file": ("s.png", png(), "image/png")},
    )
    assert sig.status_code == 201, sig.text
    sig = sig.json()
    assert sig["user_id"] == me["id"]
    img = client.get(f"/api/expenses/signatures/{sig['id']}/image")
    assert img.headers["content-type"] == "image/png" and img.content.startswith(b"\x89PNG")

    # Note signée + photo du ticket : 1 page de note + 1 page de justificatif
    r = save(
        client, {**BODY, "signature_id": sig["id"]}, files={"receipt": ("ticket.jpg", _jpg(), "image/jpeg")}
    )
    assert r.status_code == 200, r.text
    assert pages(r) == 2
    eid = int(r.headers["x-expense-id"])
    e = next(x for x in client.get("/api/expenses").json() if x["id"] == eid)
    assert e["has_receipt"] and e["receipt_name"] == "ticket.jpg" and e["signature_id"] == sig["id"]
    assert e["user_id"] == me["id"] and e["employee"] == me["name"]
    assert client.get(f"/api/expenses/{eid}/receipt").content.startswith(b"\xff\xd8\xff")

    # Remplacement par un PDF de 2 pages : 1 + 2 pages ; le PDF archivé contient aussi le justificatif
    r = save(
        client,
        {**BODY, "signature_id": sig["id"]},
        files={"receipt": ("facture.pdf", pdf(2), "application/pdf")},
        expense_id=eid,
    )
    assert r.status_code == 200 and pages(r) == 3
    assert len(PdfReader(io.BytesIO(client.get(f"/api/expenses/{eid}/pdf").content)).pages) == 3

    # Fichier refusé : mauvaise extension, contenu qui ne correspond pas, PDF corrompu (l'ancien est gardé)
    assert (
        save(
            client, files={"receipt": ("x.exe", b"MZ", "application/octet-stream")}, expense_id=eid
        ).status_code
        == 400
    )
    assert (
        save(client, files={"receipt": ("x.pdf", b"GIF89a", "application/pdf")}, expense_id=eid).status_code
        == 400
    )
    bad = save(client, files={"receipt": ("x.pdf", b"%PDF-1.4 garbage", "application/pdf")}, expense_id=eid)
    assert bad.status_code == 400 and "illisible" in bad.json()["detail"]
    assert (
        next(x for x in client.get("/api/expenses").json() if x["id"] == eid)["receipt_name"] == "facture.pdf"
    )

    # Retirer le justificatif
    r = save(client, expense_id=eid, remove_receipt="true")
    assert r.status_code == 200 and pages(r) == 1
    assert client.get(f"/api/expenses/{eid}/receipt").status_code == 404

    # Signature : images non valides refusées
    assert (
        client.post(
            "/api/expenses/signatures", data={"name": "x"}, files={"file": ("s.png", b"nope", "image/png")}
        ).status_code
        == 400
    )


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
