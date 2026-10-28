import json

import httpx

from app.services import google_calendar, integrations

CAL = "abc123@group.calendar.google.com"


class FakeCalendar:
    """Google Agenda en mémoire : liste d'agendas du compte de service + événements."""

    def __init__(self, shared=(CAL,)):
        self.shared = set(shared)  # agendas partagés avec le compte de service
        self.listed: dict[str, str] = {}
        self.events: dict[str, dict] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path.removeprefix("/calendar/v3"), request.method
        body = json.loads(request.content) if request.content else {}
        if path == "/users/me/calendarList" and method == "GET":
            return httpx.Response(
                200, json={"items": [{"id": k, "summary": v} for k, v in self.listed.items()]}
            )
        if path == "/users/me/calendarList" and method == "POST":
            if body["id"] not in self.shared:
                return httpx.Response(404, json={})
            self.listed[body["id"]] = "Deva2 – Échéances"
            return httpx.Response(200, json={"id": body["id"], "summary": "Deva2 – Échéances"})
        if path.startswith(f"/calendars/{CAL}/events"):
            eid = path.rsplit("/", 1)[-1]
            if method == "POST":
                self.events[body["id"]] = body
                return httpx.Response(200, json=body)
            if method == "PUT":
                if eid not in self.events:
                    return httpx.Response(404, json={})
                self.events[eid] = body
                return httpx.Response(200, json=body)
            if method == "DELETE":
                return httpx.Response(204) if self.events.pop(eid, None) else httpx.Response(410)
        return httpx.Response(404, json={})

    def client(self, _db=None):
        return httpx.Client(base_url=google_calendar.API, transport=httpx.MockTransport(self.handler))


def setup(db, monkeypatch, fake):
    integrations.put(
        db,
        "google_service_account_json",
        json.dumps({"client_email": "hub@deva2.iam", "private_key": "k", "token_uri": "t"}),
    )
    monkeypatch.setattr(google_calendar, "_client", fake.client)


def test_choose_calendar_and_sync_deadlines(client, db, monkeypatch):
    st = client.get("/api/taxes/google-calendar").json()
    assert st["google_configured"] is False and st["calendar_id"] == ""
    fake = FakeCalendar()
    setup(db, monkeypatch, fake)
    assert client.get("/api/taxes/google-calendar").json()["service_account_email"] == "hub@deva2.iam"

    # Agenda non partagé : message clair avec l'e-mail du compte de service
    r = client.post(
        "/api/taxes/google-calendar/calendars", json={"calendar_id": "autre@group.calendar.google.com"}
    )
    assert r.status_code == 400 and "hub@deva2.iam" in r.json()["detail"]
    # Ajout puis choix de l'agenda partagé
    assert (
        client.post("/api/taxes/google-calendar/calendars", json={"calendar_id": CAL}).json()["name"]
        == "Deva2 – Échéances"
    )
    assert client.get("/api/taxes/google-calendar/calendars").json() == [
        {"id": CAL, "name": "Deva2 – Échéances"}
    ]
    assert client.put("/api/taxes/google-calendar/select", json={"calendar_id": "inconnu"}).status_code == 400

    t = client.post(
        "/api/taxes", json={"title": "TVA T1", "category": "tva", "due_date": "2027-04-20", "amount": 1200}
    ).json()
    assert fake.events == {}  # pas encore d'agenda choisi : rien n'est envoyé
    st = client.put("/api/taxes/google-calendar/select", json={"calendar_id": CAL}).json()
    assert st["calendar_name"] == "Deva2 – Échéances" and st["last_synced_at"]
    ev = fake.events[google_calendar.event_id(t["id"])]
    assert ev["start"] == {"date": "2027-04-20"} and ev["end"] == {"date": "2027-04-21"}
    assert ev["summary"] == "TVA T1 – 1200,00 €"
    assert [o["minutes"] for o in ev["reminders"]["overrides"]] == [7 * 1440, 1440]

    # Création, modification, paiement, suppression : l'agenda suit
    t2 = client.post("/api/taxes", json={"title": "CFE", "category": "cfe", "due_date": "2027-12-15"}).json()
    assert google_calendar.event_id(t2["id"]) in fake.events
    client.put(
        f"/api/taxes/{t2['id']}", json={"title": "CFE 2027", "category": "cfe", "due_date": "2027-12-16"}
    )
    assert fake.events[google_calendar.event_id(t2["id"])]["start"] == {"date": "2027-12-16"}
    client.post(f"/api/taxes/{t['id']}/paid")
    assert fake.events[google_calendar.event_id(t["id"])]["summary"].startswith("✓ ")
    client.delete(f"/api/taxes/{t2['id']}")
    assert google_calendar.event_id(t2["id"]) not in fake.events
    # Pré-remplissage d'une année : tout est envoyé
    client.post("/api/taxes/generate?year=2028")
    assert len(fake.events) == 1 + 6
    assert client.post("/api/taxes/google-calendar/sync").json()["synced"] == 7

    # Une erreur Google ne bloque pas l'échéance, elle est signalée
    fake.shared.clear()
    monkeypatch.setattr(
        google_calendar,
        "_client",
        lambda _db=None: httpx.Client(
            base_url=google_calendar.API,
            transport=httpx.MockTransport(lambda r: httpx.Response(403, json={})),
        ),
    )
    assert client.post("/api/taxes", json={"title": "X", "due_date": "2027-05-01"}).status_code == 201
    assert "hub@deva2.iam" in client.get("/api/taxes/google-calendar").json()["last_error"]

    # Arrêter la synchronisation
    assert (
        client.put("/api/taxes/google-calendar/select", json={"calendar_id": ""}).json()["calendar_id"] == ""
    )


def test_calendar_requires_google_key(client):
    r = client.post("/api/taxes/google-calendar/calendars", json={"calendar_id": CAL})
    assert r.status_code == 400 and "compte de service" in r.json()["detail"]
