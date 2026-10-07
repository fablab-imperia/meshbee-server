"""The committed api/openapi.json against the app that serves it.

Other repositories link to the committed file as the API contract, and the
exporter runs by hand — so a route or schema change that skips
`scripts.export_openapi` would leave the contract silently stale.
"""

from pathlib import Path

from scripts.export_openapi import DEFAULT_OUTPUT, render

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_the_committed_openapi_is_what_the_app_generates():
    committed = (REPO_ROOT / DEFAULT_OUTPUT).read_text(encoding="utf-8")

    assert committed == render(), (
        "api/openapi.json is stale — regenerate it with "
        "`docker-compose exec api python -m scripts.export_openapi`."
    )
