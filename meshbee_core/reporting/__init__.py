"""Error reporting: tell the maintainers about unexpected exceptions (#56).

Provider-neutral. The entry points talk to this module only. Which service
receives the reports (Rollbar today) is a backend, found by name in the
`meshbee.error_reporters` entry-point group, so another provider is one module
and one line in a `pyproject.toml`, without touching the callers.

Two ways in, one report per exception:

- `report_exception(exc, **context)`, called where an unexpected failure is
  caught (a 500 in the API, a failed save in the MQTT handler, a crashed
  script), with what is known there;
- `ReportingHandler`, a logging handler that forwards anything logged at ERROR
  with a traceback, as a safety net for the places nobody wired.

The first marks the exception, so the `logger.exception` that usually follows
it is not sent a second time. Expected outcomes (`CoreError`, 4xx) are never
sent.

Off unless switched on: `ERROR_REPORTING_ENABLED` must be true and
`ERROR_REPORTER` set. Until then, nothing is imported and nothing leaves the
server. Like the mailer, no framework and no database here.
"""

import logging
import threading
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from importlib.metadata import PackageNotFoundError, entry_points, version
from typing import Any, Protocol

from meshbee_core.config import CoreSettings
from meshbee_core.errors import CoreError

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "meshbee.error_reporters"

# A context key containing any of these (case-insensitive) is sent as SCRUBBED.
# "token" covers access, refresh, reset and invitation tokens; "email" keeps
# addresses out: a report names a user by id only.
SENSITIVE_KEYS = (
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "cookie",
    "email",
    "dsn",
    "database_url",
    "api_key",
    "apikey",
)
SCRUBBED = "[scrubbed]"

# Set on an exception once it has been sent, so the logging bridge skips it.
REPORTED_FLAG = "__meshbee_reported__"


class Reporter(Protocol):
    """What a backend provides. `build()` in each backend module returns one."""

    def report(
        self, exc: BaseException, context: dict[str, Any], person_id: str | None
    ) -> None:
        """Send one exception, with its context and the user it happened to, if any."""

    def flush(self, timeout: float) -> None:
        """Wait (up to `timeout` seconds) for reports still being sent."""


class NullReporter:
    """Reporting off: every call is a no-op."""

    def report(self, exc, context, person_id) -> None:
        pass

    def flush(self, timeout: float) -> None:
        pass


_active: Reporter = NullReporter()

# Per request: {"method", "route", "person_id"}. A mutable dict rather than one
# value per field, so `set_person` from a dependency running in FastAPI's
# threadpool (a copy of the context) reaches the same dict the request bound.
_request: ContextVar[dict[str, Any] | None] = ContextVar(
    "meshbee_reporting_request", default=None
)

# Set while a report is being sent, so a backend's own error log is not fed back.
_sending = threading.local()


# ============================================
# Setup
# ============================================


def code_version() -> str | None:
    """The release this code is (release-please keeps it equal to API_VERSION)."""
    try:
        return version("meshbee-core")
    except PackageNotFoundError:
        return None


def available_backends() -> list[str]:
    """The backend names installed in this environment."""
    return sorted(ep.name for ep in entry_points(group=ENTRY_POINT_GROUP))


def load_backend(name: str):
    """The `build` function registered as `name`, or a ValueError naming the choices."""
    found = entry_points(group=ENTRY_POINT_GROUP, name=name)
    if not found:
        choices = ", ".join(available_backends()) or "none installed"
        raise ValueError(
            f"ERROR_REPORTER={name!r} is not an installed backend (available: {choices})"
        )
    [entry_point] = list(found)
    try:
        return entry_point.load()
    except ImportError as e:
        raise ValueError(
            f"ERROR_REPORTER={name!r} needs its extra: pip install 'meshbee-core[{name}]' ({e})"
        ) from e


def setup_reporting(settings: CoreSettings, service: str) -> Reporter:
    """
    Start reporting for this process, as configured, and return the reporter.

    `service` names the process in each report: api, mqtt-handler, migrate, seed.
    A backend that cannot start (unknown name, missing extra or token) raises:
    a process asked to report must not run silently without it.
    """
    if not settings.ERROR_REPORTING_ENABLED:
        logger.info("Error reporting: off")
        return activate(NullReporter())
    if not settings.ERROR_REPORTER:
        logger.warning("Error reporting: off, ERROR_REPORTER is not set")
        return activate(NullReporter())

    build = load_backend(settings.ERROR_REPORTER)
    reporter = build(
        environment=settings.ERROR_REPORTER_ENVIRONMENT,
        code_version=code_version(),
        service=service,
    )
    activate(reporter)
    install_logging_bridge()
    logger.info(
        f"Error reporting: {settings.ERROR_REPORTER} "
        f"(environment={settings.ERROR_REPORTER_ENVIRONMENT})"
    )
    return reporter


def activate(reporter: Reporter) -> Reporter:
    """Make `reporter` the one every call goes to. Also the seam tests fake it through."""
    global _active
    _active = reporter
    return reporter


def active() -> Reporter:
    return _active


def flush(timeout: float = 5.0) -> None:
    """Wait for reports in flight; call it before the process exits."""
    try:
        _active.flush(timeout)
    except Exception as e:
        logger.warning(f"Error reporting: flush failed: {type(e).__name__}: {e}")


# ============================================
# Request context (API)
# ============================================


def bind_request(method: str, route: str | Callable[[], str]) -> None:
    """
    Start the context of one request; later reports in it carry method and route.

    `route` may be a callable, resolved only when a report is sent: the route
    template is known after routing, later than a middleware binds the request.
    """
    _request.set({"method": method, "route": route, "person_id": None})


def unbind_request() -> None:
    """Forget the bound request, so later reports carry no request context."""
    _request.set(None)


def set_person(person_id: int | str) -> None:
    """Name the authenticated user of the current request, by id only."""
    current = _request.get()
    if current is not None:
        current["person_id"] = str(person_id)


def request_context() -> tuple[dict[str, Any], str | None]:
    """The bound request's context (lazy values resolved) and its user id."""
    current = _request.get() or {}
    context = {}
    for key, value in current.items():
        if key == "person_id":
            continue
        if callable(value):
            try:
                value = value()
            except Exception:
                value = None
        if value is not None:
            context[key] = value
    return context, current.get("person_id")


# ============================================
# Reporting
# ============================================


def is_expected(exc: BaseException) -> bool:
    """
    Whether `exc` is normal traffic rather than a fault.

    A service outcome (`CoreError`), or anything carrying a status below 500,
    such as an `HTTPException` (checked by attribute: no FastAPI import here).
    """
    if isinstance(exc, CoreError):
        return True
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and status < 500


def scrub(value: Any) -> Any:
    """A copy of `value` with every sensitive key's value replaced, at any depth."""
    if isinstance(value, Mapping):
        return {
            key: SCRUBBED if is_sensitive(key) else scrub(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [scrub(item) for item in value]
    return value


def is_sensitive(key: Any) -> bool:
    lowered = str(key).lower()
    return any(word in lowered for word in SENSITIVE_KEYS)


def report_exception(exc: BaseException, **context: Any) -> bool:
    """
    Send `exc` to the active reporter, once; whether it was sent.

    Never raises: a reporter that fails is logged, and whatever was being done
    (answering a request, reading the next message) carries on.
    """
    if is_expected(exc) or getattr(exc, REPORTED_FLAG, False):
        return False
    bound, person_id = request_context()
    full_context = {**bound, **context}
    try:
        setattr(exc, REPORTED_FLAG, True)
    except AttributeError:
        pass  # A built-in exception with __slots__: it may be sent twice, no harm.
    _sending.active = True
    try:
        _active.report(exc, scrub(full_context), person_id)
    except Exception as e:
        logger.warning(f"Error reporting failed: {type(e).__name__}: {e}")
        return False
    finally:
        _sending.active = False
    return True


# ============================================
# Logging bridge
# ============================================

# What every LogRecord has; anything else on one came from `extra=`.
_RECORD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message",
    "asctime",
    "taskName",
}


class ReportingHandler(logging.Handler):
    """Forward records logged at ERROR or above *with a traceback* to the reporter."""

    def __init__(self):
        super().__init__(level=logging.ERROR)

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(_sending, "active", False) or record.name.startswith(__name__):
            return
        if not record.exc_info or record.exc_info[1] is None:
            return
        # Not the message: log lines name users by email ("Errore per a@b.it").
        # The traceback and the logger say where; `extra=` keys say what with.
        extra = {k: v for k, v in vars(record).items() if k not in _RECORD_ATTRS}
        report_exception(record.exc_info[1], **extra, logger=record.name)


def install_logging_bridge() -> ReportingHandler:
    """Attach the bridge to the root logger, replacing one attached before."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, ReportingHandler):
            root.removeHandler(handler)
    handler = ReportingHandler()
    root.addHandler(handler)
    return handler
