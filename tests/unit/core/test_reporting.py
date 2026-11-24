"""Tests for the provider-neutral error reporting (meshbee_core/reporting).

What it owns: being off unless switched on, sending only the unexpected, each
exception once, nothing sensitive, and never breaking the caller.
"""

import logging
import sys

import pytest

from meshbee_core import reporting
from meshbee_core.errors import Conflict, InvalidData, NotFound, Unavailable

logger = logging.getLogger("tests.reporting")


def bridge_installed() -> bool:
    return any(
        isinstance(h, reporting.ReportingHandler) for h in logging.getLogger().handlers
    )


@pytest.fixture
def fake_backend(monkeypatch, reporter):
    """Register `reporter` as the backend `fake`; record how it was built."""
    built = []

    def build(**kwargs):
        built.append(kwargs)
        return reporter

    real_load = reporting.load_backend
    monkeypatch.setattr(
        reporting,
        "load_backend",
        lambda name: build if name == "fake" else real_load(name),
    )
    return built


# ============================================
# The switch
# ============================================


def test_off_by_default(build_core_settings):
    """Nothing configured: nothing to send, no bridge on the root logger."""
    settings = build_core_settings()

    reporter = reporting.setup_reporting(settings, service="api")

    assert settings.ERROR_REPORTING_ENABLED is False
    assert isinstance(reporter, reporting.NullReporter)
    assert not bridge_installed()


def test_disabled_sends_nothing_even_with_a_provider_configured(
    build_core_settings, monkeypatch
):
    """
    The per-environment switch: a development `.env` may hold the provider and
    its token and still send nothing, without even loading the backend.
    """
    monkeypatch.setenv("ROLLBAR_ACCESS_TOKEN", "a-real-looking-token")
    monkeypatch.delitem(sys.modules, "meshbee_core.reporting.rollbar", raising=False)
    monkeypatch.delitem(sys.modules, "rollbar", raising=False)
    settings = build_core_settings(
        ERROR_REPORTING_ENABLED=False, ERROR_REPORTER="rollbar"
    )

    reporter = reporting.setup_reporting(settings, service="api")

    assert isinstance(reporter, reporting.NullReporter)
    assert "rollbar" not in sys.modules
    assert not bridge_installed()


def test_enabled_without_a_reporter_sends_nothing_and_says_so(
    build_core_settings, caplog
):
    """
    Production turns the switch on by default: an install that has not picked
    a provider must still start, and its log says why nothing is reported.
    """
    settings = build_core_settings(ERROR_REPORTING_ENABLED=True)

    reporter = reporting.setup_reporting(settings, service="api")

    assert isinstance(reporter, reporting.NullReporter)
    assert not bridge_installed()
    assert "ERROR_REPORTER is not set" in caplog.text


def test_an_empty_reporter_means_unset(build_core_settings):
    """compose passes `${ERROR_REPORTER:-}`."""
    assert build_core_settings(ERROR_REPORTER="").ERROR_REPORTER is None


def test_the_switch_reads_the_environment(build_core_settings, monkeypatch):
    monkeypatch.setenv("ERROR_REPORTING_ENABLED", "true")
    monkeypatch.setenv("ERROR_REPORTER", "rollbar")

    settings = build_core_settings()

    assert settings.ERROR_REPORTING_ENABLED is True
    assert settings.ERROR_REPORTER == "rollbar"


def test_enabled_builds_the_named_backend(build_core_settings, fake_backend, reporter):
    settings = build_core_settings(
        ERROR_REPORTING_ENABLED=True,
        ERROR_REPORTER="fake",
        ERROR_REPORTER_ENVIRONMENT="production",
    )

    assert reporting.setup_reporting(settings, service="mqtt-handler") is reporter

    [kwargs] = fake_backend
    assert kwargs["environment"] == "production"
    assert kwargs["service"] == "mqtt-handler"
    assert kwargs["code_version"] == reporting.code_version()
    assert reporting.active() is reporter
    assert bridge_installed()


def test_setting_up_twice_keeps_one_bridge(build_core_settings, fake_backend):
    settings = build_core_settings(ERROR_REPORTING_ENABLED=True, ERROR_REPORTER="fake")

    reporting.setup_reporting(settings, service="api")
    reporting.setup_reporting(settings, service="api")

    bridges = [
        h
        for h in logging.getLogger().handlers
        if isinstance(h, reporting.ReportingHandler)
    ]
    assert len(bridges) == 1


def test_an_unknown_backend_fails_at_startup_naming_the_installed_ones(
    build_core_settings,
):
    settings = build_core_settings(ERROR_REPORTING_ENABLED=True, ERROR_REPORTER="nope")

    with pytest.raises(ValueError, match=r"'nope'.*available: .*rollbar"):
        reporting.setup_reporting(settings, service="api")


def test_rollbar_is_registered_as_an_entry_point():
    """What `ERROR_REPORTER=rollbar` resolves to, from pyproject.toml."""
    assert "rollbar" in reporting.available_backends()


def test_the_code_version_is_the_release():
    """release-please bumps pyproject.toml and API_VERSION together."""
    from api.config import Settings

    assert reporting.code_version() == Settings.model_fields["API_VERSION"].default


# ============================================
# What is sent
# ============================================


@pytest.mark.parametrize(
    "exc",
    [
        NotFound("x"),
        Conflict("x"),
        InvalidData("x"),
        Unavailable("x"),
    ],
)
def test_service_outcomes_are_not_sent(reporter, exc):
    assert reporting.report_exception(exc) is False
    assert reporter.reports == []


@pytest.mark.parametrize("status, sent", [(400, False), (404, False), (500, True)])
def test_http_errors_are_sent_only_from_500(reporter, status, sent):
    from fastapi import HTTPException

    assert reporting.report_exception(HTTPException(status_code=status)) is sent
    assert len(reporter.reports) == int(sent)


def test_an_unexpected_error_is_sent_with_its_context(reporter):
    exc = RuntimeError("boom")

    assert reporting.report_exception(exc, operation="lettura arnie") is True

    [(sent, context, person_id)] = reporter.reports
    assert sent is exc
    assert context == {"operation": "lettura arnie"}
    assert person_id is None


def test_an_exception_is_sent_once(reporter):
    exc = RuntimeError("boom")

    reporting.report_exception(exc)
    reporting.report_exception(exc)

    assert len(reporter.reports) == 1


def test_a_failing_reporter_never_reaches_the_caller(reporter, caplog):
    def broken(*args):
        raise ConnectionError("provider down")

    reporter.report = broken

    assert reporting.report_exception(RuntimeError("boom")) is False
    assert "Error reporting failed: ConnectionError" in caplog.text


def test_flush_reaches_the_reporter_and_never_raises(reporter):
    reporting.flush()
    assert reporter.flushed == 1

    def broken(timeout):
        raise TimeoutError

    reporter.flush = broken
    reporting.flush()  # no exception


# ============================================
# Scrubbing
# ============================================


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "new_password",
        "DB_PASSWORD",
        "SMTP_PASSWORD",
        "passwd",
        "JWT_SECRET_KEY",
        "token",
        "access_token",
        "refresh_token",
        "reset_token",
        "invite_token",
        "Authorization",
        "cookie",
        "email",
        "MAIL_FROM_EMAIL",
        "dsn",
        "database_url",
        "api_key",
    ],
)
def test_sensitive_keys_are_scrubbed(reporter, key):
    reporting.report_exception(RuntimeError("boom"), **{key: "s3cr3t"})

    [(_, context, _)] = reporter.reports
    assert context[key] == reporting.SCRUBBED


def test_scrubbing_reaches_nested_values():
    scrubbed = reporting.scrub(
        {"body": {"user": {"email": "a@b.it", "nome": "Ada"}}, "list": [{"token": "t"}]}
    )

    assert scrubbed == {
        "body": {"user": {"email": reporting.SCRUBBED, "nome": "Ada"}},
        "list": [{"token": reporting.SCRUBBED}],
    }


def test_harmless_context_is_kept(reporter):
    reporting.report_exception(
        RuntimeError("boom"), topic="beehive/N1/data", id_nodo="N1"
    )

    [(_, context, _)] = reporter.reports
    assert context == {"topic": "beehive/N1/data", "id_nodo": "N1"}


# ============================================
# Request context
# ============================================


def test_the_bound_request_and_user_reach_the_report(reporter):
    reporting.bind_request("GET", lambda: "/api/arnie/{id_arnia}")
    reporting.set_person(42)

    reporting.report_exception(RuntimeError("boom"), operation="x")

    [(_, context, person_id)] = reporter.reports
    assert context == {
        "method": "GET",
        "route": "/api/arnie/{id_arnia}",
        "operation": "x",
    }
    assert person_id == "42"


def test_without_a_request_set_person_is_ignored(reporter):
    reporting.set_person(42)

    reporting.report_exception(RuntimeError("boom"))

    [(_, context, person_id)] = reporter.reports
    assert context == {}
    assert person_id is None


def test_a_broken_lazy_route_does_not_stop_the_report(reporter):
    def broken():
        raise KeyError("route")

    reporting.bind_request("POST", broken)

    reporting.report_exception(RuntimeError("boom"))

    [(_, context, _)] = reporter.reports
    assert context == {"method": "POST"}


# ============================================
# Logging bridge
# ============================================


@pytest.fixture
def bridge(reporter):
    handler = reporting.install_logging_bridge()
    yield reporter
    logging.getLogger().removeHandler(handler)


def test_a_logged_traceback_is_sent(bridge):
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logger.exception("Qualcosa è andato storto", extra={"id_nodo": "N1"})

    [(exc, context, _)] = bridge.reports
    assert str(exc) == "boom"
    assert context == {"logger": "tests.reporting", "id_nodo": "N1"}


def test_the_log_message_is_not_sent(bridge):
    """Log lines name users by email; the traceback says where it happened."""
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logger.exception("Errore per ada@example.org")

    [(_, context, _)] = bridge.reports
    assert "ada@example.org" not in repr(context)


def test_an_error_without_a_traceback_is_not_sent(bridge):
    logger.error("Health check failed: connection refused")

    assert bridge.reports == []


def test_a_warning_is_not_sent(bridge):
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logger.warning("solo un avviso", exc_info=True)

    assert bridge.reports == []


def test_an_exception_reported_explicitly_is_not_sent_again_by_its_log(bridge):
    """db_operation reports with context, then logs: one report, the rich one."""
    try:
        raise RuntimeError("boom")
    except RuntimeError as e:
        reporting.report_exception(e, operation="x")
        logger.exception("Errore x")

    [(_, context, _)] = bridge.reports
    assert context == {"operation": "x"}


def test_a_logged_service_outcome_is_not_sent(bridge):
    try:
        raise NotFound("arnia")
    except NotFound:
        logger.exception("not found")

    assert bridge.reports == []


def test_a_backend_logging_its_own_failure_is_not_fed_back(bridge):
    """A provider SDK that logs an error while sending must not loop."""

    def logs_while_sending(exc, context, person_id):
        bridge.reports.append((exc, context, person_id))
        try:
            raise ConnectionError("provider down")
        except ConnectionError:
            logging.getLogger("rollbar").exception("send failed")

    bridge.report = logs_while_sending

    reporting.report_exception(RuntimeError("boom"))

    assert len(bridge.reports) == 1
