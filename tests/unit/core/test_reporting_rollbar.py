"""Tests for the Rollbar backend (meshbee_core/reporting/rollbar.py).

The SDK is never initialised for real: `rollbar.init` and `report_exc_info` are
recorded instead, so nothing leaves the test. What is checked is the
configuration that keeps private data on the server.
"""

import pytest
from pydantic import ValidationError

from meshbee_core import reporting
from meshbee_core.reporting import rollbar as backend


@pytest.fixture
def sdk(monkeypatch):
    calls = {"init": [], "report": [], "wait": 0}

    def init(token, **kwargs):
        calls["init"].append((token, kwargs))

    def report_exc_info(exc_info, **kwargs):
        calls["report"].append((exc_info, kwargs))

    def wait():
        calls["wait"] += 1

    monkeypatch.setattr(backend.rollbar, "init", init)
    monkeypatch.setattr(backend.rollbar, "report_exc_info", report_exc_info)
    monkeypatch.setattr(backend.rollbar, "wait", wait)
    return calls


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("ROLLBAR_ACCESS_TOKEN", "post-server-item-token")


def build(**overrides):
    return backend.build(
        **{
            "environment": "production",
            "code_version": "2.1.1",
            "service": "api",
            **overrides,
        }
    )


def test_the_sdk_is_configured_to_keep_private_data_home(sdk, token):
    build()

    [(sent_token, config)] = sdk["init"]
    assert sent_token == "post-server-item-token"
    assert config["environment"] == "production"
    assert config["code_version"] == "2.1.1"
    # pyrollbar's defaults would send frame locals (route arguments hold
    # passwords and emails) and the client IP, and reconfigure logging.
    assert config["locals"] == {"enabled": False}
    assert config["capture_ip"] is False
    assert config["capture_email"] is False
    assert config["capture_username"] is False
    assert config["include_request_body"] is False
    assert config["allow_logging_basic_config"] is False
    assert config["handler"] == "thread"


def test_scrub_fields_extend_rollbar_s_own(sdk, token):
    """Passing scrub_fields replaces the SDK's list, so its defaults are kept explicitly."""
    build()

    [(_, config)] = sdk["init"]
    fields = config["scrub_fields"]
    assert set(backend.DEFAULT_SCRUB_FIELDS) <= set(fields)
    assert set(reporting.SENSITIVE_KEYS) <= set(fields)
    assert {"refresh_token", "db_password", "smtp_password"} <= set(fields)
    assert len(fields) == len(set(fields))


def test_a_report_carries_the_traceback_context_and_user_id_only(sdk, token):
    reporter = build()
    try:
        raise RuntimeError("boom")
    except RuntimeError as e:
        exc = e

    reporter.report(exc, {"route": "/api/arnie", "operation": "x"}, "42")

    [(exc_info, kwargs)] = sdk["report"]
    assert exc_info == (RuntimeError, exc, exc.__traceback__)
    # No request object: Rollbar would collect headers, query and IP from it.
    assert kwargs["request"] is None
    assert kwargs["extra_data"] == {
        "service": "api",
        "route": "/api/arnie",
        "operation": "x",
    }
    assert kwargs["payload_data"] == {"context": "/api/arnie", "person": {"id": "42"}}


def test_without_a_route_or_user_the_service_is_the_context(sdk, token):
    reporter = build(service="mqtt-handler")

    reporter.report(RuntimeError("boom"), {"topic": "beehive/N1/data"}, None)

    [(_, kwargs)] = sdk["report"]
    assert kwargs["payload_data"] == {"context": "mqtt-handler"}


def test_flush_waits_for_the_sender_threads(sdk, token):
    build().flush(5)

    assert sdk["wait"] == 1


@pytest.mark.parametrize("value", [None, ""])
def test_the_token_is_required(sdk, monkeypatch, value):
    """compose passes `${ROLLBAR_ACCESS_TOKEN:-}`: unset arrives as ""."""
    if value is None:
        monkeypatch.delenv("ROLLBAR_ACCESS_TOKEN", raising=False)
    else:
        monkeypatch.setenv("ROLLBAR_ACCESS_TOKEN", value)

    with pytest.raises(ValidationError, match="ROLLBAR_ACCESS_TOKEN"):
        backend.RollbarSettings(_env_file=None)


def test_setup_through_the_entry_point(sdk, token, build_core_settings):
    """ERROR_REPORTER=rollbar, end to end through the facade."""
    settings = build_core_settings(
        ERROR_REPORTING_ENABLED=True,
        ERROR_REPORTER="rollbar",
        ERROR_REPORTER_ENVIRONMENT="staging",
    )

    reporter = reporting.setup_reporting(settings, service="seed")

    assert isinstance(reporter, backend.RollbarReporter)
    [(_, config)] = sdk["init"]
    assert config["environment"] == "staging"
