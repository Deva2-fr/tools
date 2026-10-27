def test_company_contact_crud_and_filter(client):
    c = client.post("/api/crm/companies", json={"name": "Acme", "kind": "prospect", "city": "Lyon"}).json()
    ct = client.post(
        "/api/crm/contacts",
        json={"company_id": c["id"], "first_name": "Ada", "last_name": "L", "email": " ADA@Acme.fr "},
    ).json()
    assert ct["email"] == "ada@acme.fr"
    client.post("/api/crm/contacts", json={"last_name": "Autre"})
    assert len(client.get(f"/api/crm/contacts?company_id={c['id']}").json()) == 1
    assert client.get("/api/crm/companies?q=lyon").json()[0]["name"] == "Acme"
    assert client.get("/api/crm/companies?q=zzz").json() == []
    assert (
        client.put(f"/api/crm/companies/{c['id']}", json={"name": "Acme SA", "kind": "client"}).json()["name"]
        == "Acme SA"
    )
    assert client.delete(f"/api/crm/companies/{c['id']}").status_code == 204
    # le contact survit à la suppression de la société
    assert client.get("/api/crm/contacts?q=ada").json()[0]["company_id"] is None


def test_invalid_kind_rejected(client):
    assert client.post("/api/crm/companies", json={"name": "X", "kind": "hacker"}).status_code == 422


def test_pipeline_move_and_summary(client):
    c = client.post("/api/crm/companies", json={"name": "Acme", "kind": "prospect"}).json()
    o = client.post(
        "/api/crm/opportunities",
        json={"title": "Refonte", "company_id": c["id"], "amount": 10000, "probability": 50},
    ).json()
    s = client.get("/api/crm/pipeline/summary").json()
    assert s["open_amount"] == 10000 and s["forecast"] == 5000
    moved = client.post(f"/api/crm/opportunities/{o['id']}/stage", json={"stage": "won"}).json()
    assert moved["stage"] == "won" and moved["probability"] == 100
    assert client.get("/api/crm/companies").json()[0]["kind"] == "client"
    acts = client.get(f"/api/crm/activities?opportunity_id={o['id']}").json()
    assert "won" in acts[0]["subject"]
    assert client.get("/api/crm/pipeline/summary").json()["won_amount"] == 10000
    assert client.post(f"/api/crm/opportunities/{o['id']}/stage", json={"stage": "nope"}).status_code == 422


def test_tasks_and_activities(client):
    t = client.post("/api/crm/tasks", json={"title": "Rappeler", "due_date": "2026-01-01"}).json()
    assert client.post(f"/api/crm/tasks/{t['id']}/toggle").json()["done"] is True
    a = client.post("/api/crm/activities", json={"kind": "call", "subject": "Appel"}).json()
    assert a["created_by"] == "admin@test.fr"
    assert client.delete(f"/api/crm/activities/{a['id']}").status_code == 204


def test_csv_import_dedupes_and_reports_errors(client):
    csv_text = "name;city;kind\nAlpha;Paris;client\nBeta;Lille;prospect\nAlpha;Paris;client\n;Nowhere;client\nGamma;Nice;bogus\n"
    r = client.post("/api/crm/companies/import", json={"csv": csv_text}).json()
    assert (
        r["created"] == 2
    )  # Alpha (doublon ignoré) + Beta ; la ligne sans nom et le type invalide sont rejetés
    assert len(r["errors"]) == 2
    r2 = client.post("/api/crm/companies/import", json={"csv": csv_text}).json()
    assert r2["created"] == 0


def test_csv_export_neutralises_formulas(client):
    client.post("/api/crm/companies", json={"name": '=HYPERLINK("http://evil")'})
    body = client.get("/api/crm/companies/export/csv").text
    assert "'=HYPERLINK" in body and ";=HYPERLINK" not in body


def test_overview_hides_money_from_members(client, as_role):
    c = client.post("/api/crm/companies", json={"name": "Acme", "email": "info@acme.fr"}).json()
    client.post("/api/crm/contacts", json={"company_id": c["id"], "email": "bob@acme.fr", "last_name": "Bob"})
    member = as_role("member")
    ov = member.get(f"/api/crm/companies/{c['id']}/overview").json()
    assert ov["money_visible"] is False and ov["invoiced"] is None and ov["documents"] == []
    assert client.get(f"/api/crm/companies/{c['id']}/overview").json()["money_visible"] is True


def test_global_search(client):
    client.post("/api/crm/companies", json={"name": "Zorglub SARL"})
    assert client.get("/api/crm/search?q=zorg").json()[0]["type"] == "Société"
    assert client.get("/api/crm/search?q=z").json() == []
