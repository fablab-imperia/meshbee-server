#!/usr/bin/env python3
"""
Export the FastAPI schema to a file.

FastAPI already serves the schema at runtime on `/openapi.json`, but a URL that
only exists while the stack is up cannot be linked from another repository. This
writes the same document to disk so `api/openapi.json` can be committed and
referenced as the API contract:
https://github.com/fablab-imperia/meshbee/blob/main/docs/contract/api.md

Run it inside the container — `api/config.py` builds `Settings` at import, so on
the host it fails before reaching the schema:

    docker-compose exec api python -m scripts.export_openapi   (or: make openapi)

The output is sorted and indented so regenerating an unchanged API produces an
empty diff.
"""
import json
import sys
from pathlib import Path

from api.main import app

# Relative to the repo root, which is the working directory in the api container.
DEFAULT_OUTPUT = Path("api/openapi.json")


def render() -> str:
    """The exact bytes of the artifact, so a test can compare without guessing."""
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def export(destination: Path) -> None:
    destination.write_text(render(), encoding="utf-8")
    print(f"OpenAPI {app.openapi_version} scritto in {destination}")


if __name__ == "__main__":
    export(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT)
