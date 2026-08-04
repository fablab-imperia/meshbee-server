"""Tests for the pydantic models (api/models.py).

Scope: the validation *we* declare — the custom email/lettura validators, the
Field bounds, and the defaults that have to agree with database/init.sql.
Pydantic's own machinery (required fields, datetime parsing) is not retested.
"""
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from models import (
    ArniaBase,
    ArniaResponse,
    ArniaUpdate,
    AttivitaQueryParams,
    LetturaBase,
    LettureQueryParams,
    PasswordChange,
    Token,
    UserCreate,
    UserLogin,
    UserResponse,
    UserUpdate,
    UtenteArniaCreate,
)


def arnia(**overrides):
    """ArniaBase with the two required identifiers filled in."""
    return ArniaBase(id_nodo="NODE001", id_sensore_fisico="SENSOR01", **overrides)


# ============================================
# Email validation
# ============================================


def test_email_is_normalised():
    """Emails are trimmed and lowercased, so lookups match regardless of input casing."""
    user = UserCreate(
        email="  ApiColtore@Example.ORG  ", nome="Giulia", cognome="Rossi", password="secret123"
    )

    assert user.email == "apicoltore@example.org"


def test_internal_domains_are_accepted():
    """`.local` domains must pass: it is why email is a plain str and not EmailStr."""
    user = UserCreate(
        email="admin@beehive.local", nome="Admin", cognome="Admin", password="secret123"
    )

    assert user.email == "admin@beehive.local"


@pytest.mark.parametrize(
    "invalid_email",
    [
        "no-at-sign",           # missing @
        "@example.org",         # empty local part
        "utente@",              # empty domain
        "utente@nodot",         # domain without a dot
        "",                     # empty string
    ],
)
def test_malformed_emails_are_rejected(invalid_email):
    """The minimal format check refuses anything that cannot be an address."""
    with pytest.raises(ValidationError):
        UserCreate(email=invalid_email, nome="A", cognome="B", password="secret123")


def test_email_validation_is_inherited_by_the_response_model():
    """UserResponse extends UserBase, so data leaving the API is normalised too."""
    user = UserResponse(
        email="ApiColtore@Example.ORG",
        nome="Giulia",
        cognome="Rossi",
        id_utente=1,
        ruolo="user",
        data_creazione=datetime(2026, 1, 1),
        attivo=True,
    )

    assert user.email == "apicoltore@example.org"


def test_login_email_is_normalised():
    """UserLogin shares UserBase's normalisation so the lookup matches what was stored."""
    assert UserLogin(email="  ApiColtore@Example.ORG  ", password="x").email == (
        "apicoltore@example.org"
    )


def test_login_email_format_is_not_validated():
    """Normalisation only: a malformed address must reach the 401, not raise here."""
    assert UserLogin(email="not-an-email", password="x").email == "not-an-email"


def test_userupdate_does_not_validate_the_email():
    """
    Known asymmetry: UserUpdate declares email as a bare Optional[str].

    It does not inherit UserBase, so an update can set an address that creation
    would have refused. Pinned so the gap is visible rather than surprising.
    """
    assert UserUpdate(email="not-an-email").email == "not-an-email"


# ============================================
# Lettura ranges
# ============================================


@pytest.mark.parametrize(
    "field, value",
    [
        ("temperatura", "-50"), ("temperatura", "0"), ("temperatura", "100"),
        ("umidita", "0"), ("umidita", "100"),
        ("peso", "0"), ("peso", "42.5"),
    ],
)
def test_readings_accept_values_inside_the_range(field, value):
    """The declared bounds are inclusive."""
    lettura = LetturaBase(**{field: Decimal(value)})

    assert getattr(lettura, field) == Decimal(value)


@pytest.mark.parametrize(
    "field, value",
    [
        ("temperatura", "-50.01"), ("temperatura", "100.01"),
        ("umidita", "-0.01"), ("umidita", "100.01"),
        ("peso", "-0.01"),
    ],
)
def test_readings_reject_values_outside_the_range(field, value):
    """A sensor glitch is refused at the edge of the API, not stored."""
    with pytest.raises(ValidationError):
        LetturaBase(**{field: Decimal(value)})


def test_readings_are_all_optional():
    """A node reporting only some sensors is valid."""
    lettura = LetturaBase()

    assert (lettura.temperatura, lettura.umidita, lettura.peso) == (None, None, None)


# ============================================
# Coordinates
# ============================================


@pytest.mark.parametrize(
    "field, value",
    [
        ("latitudine", "-90"), ("latitudine", "90"), ("latitudine", "45.4642"),
        ("longitudine", "-180"), ("longitudine", "180"), ("longitudine", "9.19"),
    ],
)
def test_coordinates_accept_values_inside_the_range(field, value):
    """Bounds are inclusive, matching the CHECK constraints in init.sql."""
    assert getattr(arnia(**{field: Decimal(value)}), field) == Decimal(value)


@pytest.mark.parametrize(
    "field, value",
    [
        ("latitudine", "-90.01"), ("latitudine", "90.01"),
        ("longitudine", "-180.01"), ("longitudine", "180.01"),
    ],
)
def test_coordinates_reject_values_outside_the_range(field, value):
    """Out-of-range coordinates are refused before they reach the database."""
    with pytest.raises(ValidationError):
        arnia(**{field: Decimal(value)})


def test_coordinates_are_optional():
    """Coordinates are opt-in: an arnia without them is valid."""
    assert arnia().latitudine is None


@pytest.mark.parametrize("field, value", [("latitudine", "90.01"), ("longitudine", "180.01")])
def test_arnia_update_applies_the_same_coordinate_bounds(field, value):
    """Editing an arnia cannot bypass the bounds that creation enforces."""
    with pytest.raises(ValidationError):
        ArniaUpdate(**{field: Decimal(value)})


def test_arnia_response_does_not_constrain_coordinates():
    """
    Known asymmetry: ArniaResponse redeclares latitudine/longitudine without
    the ge/le bounds it inherits from ArniaBase, so a row already in the
    database is serialised as-is rather than raising. Pinned to make the
    override visible; it only affects output, never what gets stored.
    """
    response = ArniaResponse(
        id_nodo="NODE001",
        id_sensore_fisico="SENSOR01",
        id_arnia=1,
        data_installazione=datetime(2026, 1, 1),
        attiva=True,
        latitudine=Decimal("999"),
    )

    assert response.latitudine == Decimal("999")


# ============================================
# Password rules
# ============================================


def test_a_new_password_must_be_at_least_eight_characters():
    """Seven characters is refused."""
    with pytest.raises(ValidationError):
        PasswordChange(new_password="1234567")


def test_an_eight_character_password_is_accepted():
    """Eight is the inclusive minimum."""
    assert PasswordChange(new_password="12345678").new_password == "12345678"


def test_current_password_is_optional():
    """An admin resetting someone else's password does not supply the old one."""
    assert PasswordChange(new_password="12345678").current_password is None


# ============================================
# Defaults that mirror the database schema
# ============================================


def test_token_type_defaults_to_bearer():
    """Clients rely on the token_type field without it being sent explicitly."""
    assert Token(access_token="a", refresh_token="r").token_type == "bearer"


def test_new_users_default_to_the_user_role():
    """Matches the `utenti.ruolo` default and its CHECK (ruolo IN ('user','admin'))."""
    user = UserCreate(email="a@b.org", nome="A", cognome="B", password="secret123")

    assert user.ruolo == "user"


def test_new_associations_default_to_read_permission():
    """Matches the `utenti_arnie.permessi` default: least privilege unless asked."""
    assert UtenteArniaCreate(id_utente=1, id_arnia=1).permessi == "read"


# ============================================
# Query parameters
# ============================================


def test_letture_query_defaults():
    """Paging defaults for the readings endpoints."""
    params = LettureQueryParams()

    assert (params.limit, params.offset) == (1000, 0)


def test_attivita_query_defaults():
    """Activity listings default to a smaller page than readings."""
    params = AttivitaQueryParams()

    assert (params.limit, params.offset) == (100, 0)


@pytest.mark.parametrize(
    "model, field, value",
    [
        (LettureQueryParams, "limit", 0),        # below the minimum
        (LettureQueryParams, "limit", 10001),    # above the cap
        (LettureQueryParams, "offset", -1),
        (AttivitaQueryParams, "limit", 0),
        (AttivitaQueryParams, "limit", 1001),    # lower cap than letture
        (AttivitaQueryParams, "offset", -1),
    ],
)
def test_query_paging_bounds_are_enforced(model, field, value):
    """The caps stop a client asking for an unbounded result set."""
    with pytest.raises(ValidationError):
        model(**{field: value})


# ============================================
# ORM mode
# ============================================


def test_response_models_can_be_built_from_database_rows():
    """
    from_attributes lets endpoints hand a row object straight to the model.

    Guards the pending `class Config` → `ConfigDict` migration: this must keep
    working when the deprecated class-based config is replaced.
    """
    row = SimpleNamespace(
        id_utente=1,
        email="apicoltore@example.org",
        nome="Giulia",
        cognome="Rossi",
        ruolo="user",
        data_creazione=datetime(2026, 1, 1),
        data_attivazione=None,
        data_disattivazione=None,
        ultimo_accesso=None,
        attivo=True,
    )

    assert UserResponse.model_validate(row).email == "apicoltore@example.org"
