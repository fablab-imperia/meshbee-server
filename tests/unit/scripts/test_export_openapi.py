"""Tests for the OpenAPI exporter (scripts/export_openapi.py).

That the committed file matches the app is tests/unit/api/test_openapi.py.
These cover writing it: the file is the contract other repositories link to.
"""

import json
import runpy
import sys

from scripts import export_openapi


def test_export_writes_exactly_what_render_produces(tmp_path, capsys):
    """The staleness test compares against render(), so the file must be its bytes."""
    destination = tmp_path / "openapi.json"

    export_openapi.export(destination)

    assert destination.read_text(encoding="utf-8") == export_openapi.render()
    assert str(destination) in capsys.readouterr().out


def test_the_output_is_stable_and_diffable():
    """Sorted keys, indented, a final newline: an unchanged API regenerates no diff."""
    rendered = export_openapi.render()

    assert rendered.endswith("}\n")
    assert (
        rendered
        == json.dumps(
            json.loads(rendered), indent=2, sort_keys=True, ensure_ascii=False
        )
        + "\n"
    )


def test_non_ascii_text_is_written_as_is():
    """The Italian descriptions stay readable in review, not \\u-escaped."""
    assert "attività" in export_openapi.render()


def test_the_script_writes_to_the_path_it_is_given(tmp_path, monkeypatch):
    """`python -m scripts.export_openapi <path>` lets CI write to a scratch file."""
    destination = tmp_path / "contract.json"
    monkeypatch.setattr(sys, "argv", ["export_openapi", str(destination)])

    # Run it fresh, as `python -m` does, rather than over the imported copy.
    monkeypatch.delitem(sys.modules, "scripts.export_openapi")

    runpy.run_module("scripts.export_openapi", run_name="__main__")

    assert destination.read_text(encoding="utf-8") == export_openapi.render()
