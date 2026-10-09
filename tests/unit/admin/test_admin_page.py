"""The static admin page (admin/), which the API mounts at /admin."""

import re

import pytest
from fastapi.testclient import TestClient

from api import main

ADMIN_DIR = main.ADMIN_DIR


@pytest.fixture
def client():
    # Not entered as a context manager: the lifespan would open the DB pool,
    # and serving static files needs no database.
    return TestClient(main.app)


def test_the_admin_page_is_served_at_admin(client):
    """The page is the whole frontend; if the mount breaks there is nothing to fall back on."""
    response = client.get("/admin/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'x-data="admin()"' in response.text


def test_every_asset_the_page_references_is_served(client):
    """The vendored libraries carry their version in the file name, so a bump
    that renames the file without updating index.html would load a blank page."""
    html = (ADMIN_DIR / "index.html").read_text(encoding="utf-8")
    assets = re.findall(r'(?:src|href)="([^"#:]+\.(?:js|css))"', html)

    assert assets, "index.html references no local assets"
    for asset in assets:
        assert client.get(f"/admin/{asset}").status_code == 200, asset


def test_the_page_never_inserts_markup():
    """Users, hives and apiaries are named by users. The page must only ever
    show them through x-text, which escapes; x-html or innerHTML would let a
    hive called `<img onerror=...>` run script with the admin's token."""
    # Every page file, not vendor/: the scripts are split by feature.
    pages = ["index.html", *sorted(p.name for p in ADMIN_DIR.glob("*.js"))]
    assert "admin.js" in pages and len(pages) > 2, pages
    for name in pages:
        source = (ADMIN_DIR / name).read_text(encoding="utf-8")
        assert "x-html" not in source, name
        assert "innerHTML" not in source, name
        assert "outerHTML" not in source, name
