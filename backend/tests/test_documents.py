from app.models import User

PDF = b"%PDF-1.4 test"


def upload(client, name, folder_id=None):
    data = {"name": name}
    if folder_id:
        data["folder_id"] = str(folder_id)
    r = client.post("/api/files", data=data, files={"file": (f"{name}.pdf", PDF, "application/pdf")})
    assert r.status_code == 201, r.text
    return r.json()


def test_folders_tree_upload_move_and_search(client):
    rh = client.post("/api/files/folders", json={"name": "RH"}).json()
    contrats = client.post("/api/files/folders", json={"name": "Contrats", "parent_id": rh["id"]}).json()
    assert (
        client.post("/api/files/folders", json={"name": "rh"}).status_code == 400
    )  # doublon (casse ignorée)
    assert (
        client.post("/api/files/folders", json={"name": "Contrats"}).status_code == 201
    )  # autre niveau : OK

    kbis = upload(client, "Kbis")
    contrat = upload(client, "Contrat Bob", contrats["id"])
    assert contrat["folder_id"] == contrats["id"]
    assert [f["name"] for f in client.get("/api/files").json()] == ["Kbis"]  # racine
    assert [f["name"] for f in client.get(f"/api/files?folder_id={contrats['id']}").json()] == ["Contrat Bob"]
    assert {f["name"] for f in client.get("/api/files?q=o").json()} == {"Contrat Bob"}  # tous dossiers

    tree = {f["name"] + str(f["parent_id"]): f for f in client.get("/api/files/folders").json()}
    assert tree[f"RH{None}"]["folders"] == 1 and tree[f"Contrats{rh['id']}"]["files"] == 1

    # Déplacer un fichier, renommer un dossier, interdire les boucles et la suppression d'un dossier non vide
    moved = client.put(f"/api/files/{kbis['id']}/folder", json={"folder_id": rh["id"]}).json()
    assert moved["folder_id"] == rh["id"]
    assert (
        client.put(
            f"/api/files/folders/{rh['id']}", json={"name": "RH", "parent_id": contrats["id"]}
        ).status_code
        == 400
    )
    r = client.put(
        f"/api/files/folders/{contrats['id']}", json={"name": "Contrats signés", "parent_id": rh["id"]}
    )
    assert r.status_code == 200 and r.json()["name"] == "Contrats signés"
    assert client.delete(f"/api/files/folders/{rh['id']}").status_code == 400
    client.put(f"/api/files/{contrat['id']}/folder", json={"folder_id": None})
    assert client.delete(f"/api/files/folders/{contrats['id']}").status_code == 204
    assert (
        client.post(
            "/api/files", data={"folder_id": "999"}, files={"file": ("x.pdf", PDF, "application/pdf")}
        ).status_code
        == 404
    )


def test_tours_only_during_first_session(client, db):
    me = client.get("/api/auth/me").json()
    assert me["tours_done"] is False  # compte neuf : première connexion
    assert client.post("/api/auth/me/tours-done").status_code == 204
    assert client.get("/api/auth/me").json()["tours_done"] is True
    assert db.get(User, me["id"]).tours_done is True


MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 64


def test_videos_upload_and_play_with_ranges(client, as_role):
    from app.routers import ops

    r = client.post("/api/files", files={"file": ("demo.mp4", MP4, "video/mp4")})
    assert r.status_code == 201, r.text
    mp4 = r.json()
    assert client.post("/api/files", files={"file": ("c.webm", WEBM, "video/webm")}).status_code == 201
    # Fausse vidéo : refusée
    assert (
        client.post("/api/files", files={"file": ("x.mp4", b"not a video at all", "video/mp4")}).status_code
        == 400
    )

    v = client.get(f"/api/files/{mp4['id']}/view")
    assert v.status_code == 200 and v.headers["content-type"] == "video/mp4"
    assert v.headers["content-disposition"].startswith("inline")
    part = client.get(f"/api/files/{mp4['id']}/view", headers={"Range": "bytes=0-9"})
    assert part.status_code == 206 and part.content == MP4[:10]
    assert as_role("member").get(f"/api/files/{mp4['id']}/view").status_code == 403

    # Taille maximale : refus et aucun fichier partiel laissé sur le disque
    before = set(ops._files_dir().iterdir())
    old = ops.MAX_VIDEO
    ops.MAX_VIDEO = 50
    try:
        big = client.post("/api/files", files={"file": ("big.mp4", MP4 + b"\x00" * 100, "video/mp4")})
    finally:
        ops.MAX_VIDEO = old
    assert big.status_code == 413 and "Mo maximum" in big.json()["detail"]
    assert set(ops._files_dir().iterdir()) == before


def test_several_files_in_a_row_land_in_the_same_folder(client):
    folder = client.post("/api/files/folders", json={"name": "Lot"}).json()
    for n in ("a", "b", "c"):
        upload(client, n, folder["id"])
    assert {f["name"] for f in client.get(f"/api/files?folder_id={folder['id']}").json()} == {"a", "b", "c"}
