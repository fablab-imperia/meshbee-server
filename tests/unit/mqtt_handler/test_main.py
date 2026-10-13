"""Tests for `python -m mqtt_handler` (mqtt_handler/__main__.py)."""

import runpy

from mqtt_handler import handler


def test_running_the_package_starts_the_handler(monkeypatch):
    """The container's CMD is `python -m mqtt_handler`; it must reach main()."""
    started = []
    monkeypatch.setattr(handler, "main", lambda: started.append(True))

    runpy.run_module("mqtt_handler", run_name="__main__")

    assert started == [True]


def test_importing_the_package_entry_point_starts_nothing(monkeypatch):
    """Only running it as a script starts the handler, not importing it."""
    started = []
    monkeypatch.setattr(handler, "main", lambda: started.append(True))

    runpy.run_module("mqtt_handler.__main__", run_name="mqtt_handler.__main__")

    assert started == []
