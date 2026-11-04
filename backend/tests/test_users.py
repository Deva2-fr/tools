from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import H

ADMIN = {"email": "admin@test.fr", "password": "CorrectHorse-Battery-9"}


def login(email, password):
    c = TestClient(app)
    c.headers.update(H)
    r = c.post("/api/auth/login", json={"email": email, "password": password})
    return c, r


def test_my_profile_name_and_email(client):
    r = client.put("/api/auth/me", json={"name": "Hugo", "email": "admin@test.fr"})
    assert r.status_code == 200 and r.json()["name"] == "Hugo"
    # Changer d'e-mail demande le mot de passe actuel
    bad = client.put("/api/auth/me", json={"name": "Hugo", "email": "hugo@deva2.fr", "current_password": "x"})
    assert bad.status_code == 400
    client.post("/api/users", json={"email": "pris@test.fr", "password": "another-long-password"})
    taken = client.put(
        "/api/auth/me", json={"name": "Hugo", "email": "pris@test.fr", "current_password": ADMIN["password"]}
    )
    assert taken.status_code == 409
    ok = client.put(
        "/api/auth/me", json={"name": "Hugo", "email": "Hugo@Deva2.fr", "current_password": ADMIN["password"]}
    )
    assert ok.status_code == 200 and ok.json()["email"] == "hugo@deva2.fr"
    assert client.get("/api/auth/me").json()["email"] == "hugo@deva2.fr"  # session courante gardée
    assert login("hugo@deva2.fr", ADMIN["password"])[1].status_code == 200


def test_password_change_closes_other_sessions(client):
    other, r = login(**ADMIN)
    assert r.status_code == 200
    same = client.post(
        "/api/auth/password", json={"current_password": ADMIN["password"], "new_password": ADMIN["password"]}
    )
    assert same.status_code == 400
    r = client.post(
        "/api/auth/password",
        json={"current_password": ADMIN["password"], "new_password": "Brand-New-Password-42"},
    )
    assert r.status_code == 200
    assert client.get("/api/auth/me").status_code == 200  # cet appareil reste connecté
    assert other.get("/api/auth/me").status_code == 401  # l'autre session est fermée
    assert login("admin@test.fr", "Brand-New-Password-42")[1].status_code == 200


def test_admin_edits_resets_and_disables_users(client, as_role, db):
    member = as_role("member", "bob@test.fr")
    uid = member.get("/api/auth/me").json()["id"]

    r = client.put(f"/api/users/{uid}", json={"name": "Bob", "email": "bob@test.fr", "role": "manager"})
    assert r.status_code == 200 and r.json()["role"] == "manager" and r.json()["name"] == "Bob"
    assert member.get("/api/auth/me").json()["role"] == "manager"  # rôle changé : session gardée

    # Mot de passe oublié : provisoire choisi par l'admin, anciennes sessions fermées
    assert client.post(f"/api/users/{uid}/password", json={"new_password": "short"}).status_code == 422
    assert (
        client.post(f"/api/users/{uid}/password", json={"new_password": "Provisoire-2026!"}).status_code
        == 204
    )
    assert member.get("/api/auth/me").status_code == 401
    bob, r = login("bob@test.fr", "Provisoire-2026!")
    assert r.status_code == 200

    # 2FA perdue
    from app.models import User

    u = db.get(User, uid)
    u.totp_enabled, u.totp_secret_enc = True, "x"
    db.commit()
    assert client.post(f"/api/users/{uid}/reset-2fa").status_code == 204
    db.refresh(u)
    assert u.totp_enabled is False and u.totp_secret_enc is None

    # Désactivation : plus de connexion, session fermée, historique gardé
    r = client.put(
        f"/api/users/{uid}",
        json={"name": "Bob", "email": "bob@test.fr", "role": "manager", "is_active": False},
    )
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert bob.get("/api/auth/me").status_code == 401
    assert login("bob@test.fr", "Provisoire-2026!")[1].status_code == 401

    # Journal : actions tracées, jamais de mot de passe
    log = str(client.get("/api/users/audit/log").json())
    assert "user_password_reset" in log and "user_2fa_reset" in log and "désactivé" in log
    assert "Provisoire-2026!" not in log

    # Réservé aux admins
    assert (
        as_role("manager", "m@test.fr")
        .put(f"/api/users/{uid}", json={"email": "x@y.fr", "role": "admin"})
        .status_code
        == 403
    )


def test_last_admin_is_protected(client):
    me = client.get("/api/auth/me").json()
    body = {"name": "", "email": me["email"], "role": "member"}
    assert client.put(f"/api/users/{me['id']}", json=body).status_code == 400
    assert (
        client.put(f"/api/users/{me['id']}", json={**body, "role": "admin", "is_active": False}).status_code
        == 400
    )
    # Un autre admin : on peut le rétrograder (il en reste un), pas le dernier
    r = client.post(
        "/api/users", json={"email": "a2@test.fr", "password": "another-long-password", "role": "admin"}
    )
    a2 = r.json()["id"]
    assert client.put(f"/api/users/{a2}", json={"email": "a2@test.fr", "role": "member"}).status_code == 200
    assert client.put(f"/api/users/{a2}", json={"email": "a2@test.fr", "role": "admin"}).status_code == 200
    assert client.delete(f"/api/users/{a2}").status_code == 204
    # E-mail déjà pris
    client.post("/api/users", json={"email": "c@test.fr", "password": "another-long-password"})
    r = client.post("/api/users", json={"email": "d@test.fr", "password": "another-long-password"})
    assert (
        client.put(f"/api/users/{r.json()['id']}", json={"email": "c@test.fr", "role": "member"}).status_code
        == 409
    )
