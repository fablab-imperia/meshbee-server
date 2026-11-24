"""The hive photo (#3): /api/user/arnie/{id_arnia}/foto."""

import io

from PIL import Image

from meshbee_core.limits import FOTO_MAX_BYTES
from tests.conftest import image_bytes


def upload(client, id_arnia, data=None, filename="hive.jpg", content_type="image/jpeg"):
    return client.put(
        f"/api/user/arnie/{id_arnia}/foto",
        files={"file": (filename, data or image_bytes(), content_type)},
    )


def stored_files(storage):
    return sorted(p for p in storage.root.rglob("*") if p.is_file())


# ============================================
# PUT
# ============================================


def test_an_uploaded_photo_becomes_the_hives(as_user, utente_con_arnia, storage, db):
    utente, arnia = utente_con_arnia("manager")

    response = upload(as_user(utente), arnia["id_arnia"])

    assert response.status_code == 200
    foto = response.json()
    assert foto["content_type"] == "image/webp"
    assert foto["id_utente_caricamento"] == utente["id_utente"]
    assert "chiave" not in foto
    db.execute("SELECT id_foto FROM arnie WHERE id_arnia = %s", (arnia["id_arnia"],))
    assert db.fetchone()["id_foto"] == foto["id_allegato"]
    assert len(stored_files(storage)) == 1


def test_a_new_photo_replaces_the_old_one_and_its_file(
    as_user, utente_con_arnia, storage, db
):
    """One photo per hive: the previous file must not linger on disk."""
    utente, arnia = utente_con_arnia("owner")
    client = as_user(utente)
    first = upload(client, arnia["id_arnia"]).json()

    second = upload(client, arnia["id_arnia"], image_bytes(fmt="PNG")).json()

    assert second["id_allegato"] != first["id_allegato"]
    db.execute("SELECT id_allegato FROM allegati")
    assert [r["id_allegato"] for r in db.fetchall()] == [second["id_allegato"]]
    assert len(stored_files(storage)) == 1


def test_a_file_that_is_not_an_image_is_refused_and_not_kept(
    as_user, utente_con_arnia, storage, db
):
    utente, arnia = utente_con_arnia("owner")

    response = upload(
        as_user(utente), arnia["id_arnia"], b"%PDF-1.7", "x.jpg", "image/jpeg"
    )

    assert response.status_code == 400
    db.execute("SELECT count(*) AS n FROM allegati")
    assert db.fetchone()["n"] == 0
    assert stored_files(storage) == []


def test_a_photo_over_the_size_limit_is_refused(as_user, utente_con_arnia, storage):
    """Refused by size alone, before anything tries to decode it."""
    utente, arnia = utente_con_arnia("owner")

    response = upload(
        as_user(utente), arnia["id_arnia"], b"\xff" * (FOTO_MAX_BYTES + 1)
    )

    assert response.status_code == 413
    assert stored_files(storage) == []


def test_a_photo_at_the_size_limit_is_not_refused_for_its_size(
    as_user, utente_con_arnia
):
    """The limit is 5 MB of file; the multipart framing around it must not count."""
    utente, arnia = utente_con_arnia("owner")

    response = upload(as_user(utente), arnia["id_arnia"], b"\xff" * FOTO_MAX_BYTES)

    assert response.status_code == 400  # not an image, but not too large


def test_uploading_to_a_hive_that_does_not_exist_is_404_and_keeps_nothing(
    as_user, make_utente, storage
):
    """An admin clears the access check for any id, so the service must catch it."""
    response = upload(as_user(make_utente(ruolo="admin")), 999999)

    assert response.status_code == 404
    assert stored_files(storage) == []


# ============================================
# GET
# ============================================


def test_the_photo_is_served_as_webp_with_its_id_as_etag(as_user, utente_con_arnia):
    owner, arnia = utente_con_arnia("owner")
    foto = upload(as_user(owner), arnia["id_arnia"]).json()

    response = as_user(owner).get(f"/api/user/arnie/{arnia['id_arnia']}/foto")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    assert response.headers["etag"] == f'"{foto["id_allegato"]}"'
    assert "private" in response.headers["cache-control"]
    assert Image.open(io.BytesIO(response.content)).format == "WEBP"


def test_a_hive_without_a_photo_answers_404(as_user, utente_con_arnia):
    utente, arnia = utente_con_arnia("viewer")

    response = as_user(utente).get(f"/api/user/arnie/{arnia['id_arnia']}/foto")

    assert response.status_code == 404


def test_the_hive_carries_its_photo_id(as_user, utente_con_arnia):
    """What a client lists hives with tells it which have a photo, and which one."""
    utente, arnia = utente_con_arnia("owner")
    client = as_user(utente)
    assert client.get(f"/api/user/arnie/{arnia['id_arnia']}").json()["id_foto"] is None

    foto = upload(client, arnia["id_arnia"]).json()

    assert (
        client.get(f"/api/user/arnie/{arnia['id_arnia']}").json()["id_foto"]
        == (foto["id_allegato"])
    )
    assert client.get("/api/user/arnie").json()[0]["id_foto"] == foto["id_allegato"]


# ============================================
# DELETE
# ============================================


def test_deleting_the_photo_removes_it_and_its_file(
    as_user, utente_con_arnia, storage, db
):
    utente, arnia = utente_con_arnia("owner")
    client = as_user(utente)
    upload(client, arnia["id_arnia"])

    response = client.delete(f"/api/user/arnie/{arnia['id_arnia']}/foto")

    assert response.status_code == 200
    assert client.get(f"/api/user/arnie/{arnia['id_arnia']}/foto").status_code == 404
    assert client.get(f"/api/user/arnie/{arnia['id_arnia']}").json()["id_foto"] is None
    db.execute("SELECT count(*) AS n FROM allegati")
    assert db.fetchone()["n"] == 0
    assert stored_files(storage) == []


def test_deleting_a_photo_that_is_not_there_answers_404(as_user, utente_con_arnia):
    utente, arnia = utente_con_arnia("owner")

    response = as_user(utente).delete(f"/api/user/arnie/{arnia['id_arnia']}/foto")

    assert response.status_code == 404
