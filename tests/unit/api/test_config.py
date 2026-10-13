"""Tests for the API settings (api/config.py).

The database half lives in meshbee_core and is covered by
tests/unit/core/test_config.py; what matters here is the API-only fields and
that subclassing really does carry the shared ones through.
"""

import pytest
from pydantic import ValidationError

from api.config import Settings, get_settings


def test_defaults_are_applied(build_settings):
    """Without any environment variable, the declared defaults are used."""
    settings = build_settings()

    assert settings.JWT_ALGORITHM == "HS256"
    assert settings.ACCESS_TOKEN_EXPIRE_MINUTES == 30
    assert settings.REFRESH_TOKEN_EXPIRE_DAYS == 7
    assert settings.CORS_ORIGINS == ["*"]


def test_the_shared_database_settings_are_inherited(build_settings):
    """
    Settings subclasses CoreSettings, so the API keeps one settings object.

    Asserted here because the split is invisible at the call site: `database.py`
    and every DB_* reference in the API rely on these fields still being present.
    """
    settings = build_settings()

    assert settings.DB_HOST == "localhost"
    assert settings.DB_PORT == 5432
    assert settings.DB_NAME == "beehive_iot"
    assert settings.DB_USER == "beehive_user"
    assert settings.database_url.startswith("postgresql+psycopg://")


@pytest.mark.parametrize("missing_field", ["DB_PASSWORD", "JWT_SECRET_KEY"])
def test_missing_secret_fails_loudly(monkeypatch, required_env, missing_field):
    """Secrets have no default on purpose: startup must fail, not run with an empty value."""
    monkeypatch.delenv(missing_field)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert (missing_field,) in [error["loc"] for error in exc_info.value.errors()]


def test_secrets_are_not_exposed_by_repr(build_settings):
    """A leaked settings dump (logs, tracebacks) must not reveal the secrets."""
    settings = build_settings(DB_PASSWORD="s3cr3t-db", JWT_SECRET_KEY="s3cr3t-jwt")

    assert "s3cr3t-db" not in repr(settings)
    assert "s3cr3t-jwt" not in repr(settings)
    assert settings.JWT_SECRET_KEY.get_secret_value() == "s3cr3t-jwt"


def test_cors_origins_is_read_as_a_json_list(monkeypatch, required_env):
    """CORS_ORIGINS is a list field: the environment must carry a JSON array."""
    monkeypatch.setenv("CORS_ORIGINS", '["https://a.example", "https://b.example"]')

    assert Settings(_env_file=None).CORS_ORIGINS == [
        "https://a.example",
        "https://b.example",
    ]


def test_environment_lookup_is_case_sensitive(monkeypatch, required_env):
    """case_sensitive=True: a lowercase variable is not picked up."""
    monkeypatch.setenv("db_name", "lowercase_db")

    assert Settings(_env_file=None).DB_NAME == "beehive_iot"


def test_unrelated_environment_variables_are_ignored(monkeypatch, required_env):
    """extra="ignore": the seed/mqtt variables sharing the environment must not break Settings."""
    monkeypatch.setenv("ADMIN_PASSWORD", "whatever")
    monkeypatch.setenv("MQTT_BROKER", "mosquitto")

    settings = Settings(_env_file=None)

    assert settings.DB_NAME == "beehive_iot"
    assert not hasattr(settings, "ADMIN_PASSWORD")


def test_get_settings_returns_a_cached_singleton(required_env):
    """get_settings is lru_cached: same object every call, until the cache is cleared."""
    first = get_settings()

    assert get_settings() is first
    assert first.DB_PASSWORD.get_secret_value() == "test-db-password"

    get_settings.cache_clear()
    assert get_settings() is not first


# ============================================
# Outgoing email (SMTP)
# ============================================

SMTP_ENV = {
    "SMTP_HOST": "smtp.example.org",
    "MAIL_FROM": "Meshbee <noreply@example.org>",
}


def test_email_is_disabled_by_default(build_settings):
    """An install that sets nothing keeps running exactly as before."""
    assert build_settings().smtp_config is None


def test_empty_values_count_as_unset(build_settings):
    """Compose passes an unset `${SMTP_HOST:-}` through as "", which must not enable email."""
    settings = build_settings(
        SMTP_HOST="",
        SMTP_PORT="",
        SMTP_USER="",
        SMTP_PASSWORD="",
        MAIL_FROM="",
        PUBLIC_BASE_URL="",
    )

    assert settings.smtp_config is None
    assert settings.SMTP_PORT is None
    assert settings.SMTP_PASSWORD is None
    assert settings.PUBLIC_BASE_URL is None


def test_the_smtp_config_carries_every_setting(build_settings):
    settings = build_settings(
        **SMTP_ENV,
        SMTP_PORT="2465",
        SMTP_SECURITY="ssl",
        SMTP_USER="resend",
        SMTP_PASSWORD="re_secret",
        SMTP_TIMEOUT="3.5",
    )

    smtp = settings.smtp_config
    assert (smtp.host, smtp.port, smtp.security) == ("smtp.example.org", 2465, "ssl")
    assert (smtp.username, smtp.password) == ("resend", "re_secret")
    assert smtp.sender == "Meshbee <noreply@example.org>"
    assert smtp.timeout == 3.5


@pytest.mark.parametrize(
    ("security", "port"), [("ssl", 465), ("starttls", 587), ("none", 25)]
)
def test_without_a_port_the_usual_one_for_the_security_mode_is_used(
    build_settings, security, port
):
    settings = build_settings(**SMTP_ENV, SMTP_SECURITY=security)

    assert settings.smtp_config.port == port


def test_starttls_is_the_default_security(build_settings):
    assert build_settings(**SMTP_ENV).smtp_config.security == "starttls"


def test_without_a_user_there_are_no_credentials(build_settings):
    """A relay that needs no login: the mailer is told not to log in."""
    smtp = build_settings(**SMTP_ENV).smtp_config

    assert (smtp.username, smtp.password) == (None, None)


def test_an_unknown_security_mode_fails_loudly(build_settings):
    with pytest.raises(ValidationError):
        build_settings(**SMTP_ENV, SMTP_SECURITY="tls")


def test_a_host_without_a_sender_fails_loudly(build_settings):
    """Half-configured email must stop startup, not fail on the first reset request."""
    with pytest.raises(ValidationError, match="MAIL_FROM"):
        build_settings(SMTP_HOST="smtp.example.org")


def test_a_user_without_a_password_fails_loudly(build_settings):
    with pytest.raises(ValidationError, match="SMTP_PASSWORD"):
        build_settings(**SMTP_ENV, SMTP_USER="resend")


def test_the_public_base_url_loses_its_trailing_slash(build_settings):
    """Links are built as f"{PUBLIC_BASE_URL}/path", which must not give "//path"."""
    settings = build_settings(PUBLIC_BASE_URL="https://meshbee.example.org/")

    assert settings.PUBLIC_BASE_URL == "https://meshbee.example.org"


def test_the_smtp_password_is_not_exposed_by_repr(build_settings):
    settings = build_settings(**SMTP_ENV, SMTP_USER="u", SMTP_PASSWORD="s3cr3t-smtp")

    assert "s3cr3t-smtp" not in repr(settings)
    assert "s3cr3t-smtp" not in repr(settings.smtp_config)


def test_password_reset_defaults(build_settings):
    settings = build_settings()

    assert settings.PASSWORD_RESET_EXPIRE_MINUTES == 30
    assert settings.PASSWORD_RESET_MAX_PER_ACCOUNT == 3
    assert settings.PASSWORD_RESET_MAX_PER_IP == 10


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("PASSWORD_RESET_EXPIRE_MINUTES", 0),
        ("PASSWORD_RESET_EXPIRE_MINUTES", 1441),
        ("PASSWORD_RESET_MAX_PER_ACCOUNT", 0),
        ("PASSWORD_RESET_MAX_PER_IP", 0),
    ],
)
def test_password_reset_limits_are_bounded(build_settings, field, value):
    """A reset link lives at most a day, and a cap of zero would silently disable it."""
    with pytest.raises(ValidationError):
        build_settings(**{field: value})


def test_the_share_limit_defaults_to_thirty_an_hour(build_settings):
    assert build_settings().SHARE_MAX_PER_HOUR == 30


def test_the_share_limit_must_be_positive(build_settings):
    with pytest.raises(ValidationError):
        build_settings(SHARE_MAX_PER_HOUR=0)


def test_invitation_defaults(build_settings):
    settings = build_settings()

    assert settings.INVITE_EXPIRE_DAYS == 7
    assert settings.INVITE_MAX_PER_DAY == 20
    assert settings.NOTICE_MAX_PER_DAY == 20


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("INVITE_EXPIRE_DAYS", 0),
        ("INVITE_EXPIRE_DAYS", 31),
        ("INVITE_MAX_PER_DAY", 0),
        ("NOTICE_MAX_PER_DAY", 0),
    ],
)
def test_invitation_limits_are_bounded(build_settings, field, value):
    with pytest.raises(ValidationError):
        build_settings(**{field: value})
