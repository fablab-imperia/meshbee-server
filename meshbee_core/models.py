"""
The data model: database tables and API shapes, declared once.

Each table is one family of SQLModel classes:

- `XBase` — the fields input and output share;
- `XResponse(XBase)` — the rest of the public columns, which is what the API
  returns;
- `X(XResponse, table=True)` — the table itself, adding only what never leaves
  the server (`Utente.password_hash`) and the constraints.

So every column — type, nullability, default, foreign key — is written exactly
once, on the class the table inherits it from. `XCreate` and `XUpdate` are input
shapes and stand apart: they make fields optional in their own ways, and carry
no database information.

This module is also the schema's single source for migrations: Alembic
autogenerates revisions by diffing `SQLModel.metadata` against the database,
and `tests/integration/test_migrations.py` asserts that the migration chain and
these classes produce the same catalog — CHECK constraints included, which
autogenerate does not compare.

Bounds and value sets come from `limits.py`. Constraint and index names are
spelled out so that they match the ones Postgres generated for the original
`init.sql`; a live install must not see them renamed.

Two quirks of the pinned versions shape the declarations:

- String lengths are `sa_type=String(n)`, not `max_length`, because
  `max_length` would also become an API validation rule and an OpenAPI
  `maxLength`. Over-long values are refused by the database instead.
- Decimal precision is `sa_type=Numeric(p, s)`, not `max_digits`: pydantic 2.5
  rejects `max_digits` on an Optional[Decimal].
"""

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, conlist, field_validator
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from meshbee_core.limits import (
    BATTERIA_MAX,
    BATTERIA_MIN,
    ID_MAX_LENGTH,
    LATITUDINE_MAX,
    LATITUDINE_MIN,
    LONGITUDINE_MAX,
    LONGITUDINE_MIN,
    PESO_MIN,
    RUOLI,
    RUOLI_APIARIO,
    TEMPERATURA_MAX,
    TEMPERATURA_MIN,
    TIPI_ATTIVITA,
    UMIDITA_MAX,
    UMIDITA_MIN,
    Ruolo,
    # Re-exported: the value sets are part of this module's public surface.
    RuoloApiario,
    TipoAttivita,
)

NOW = {"server_default": text("CURRENT_TIMESTAMP")}
TRUE = {"server_default": text("true")}
FALSE = {"server_default": text("false")}

ID = String(ID_MAX_LENGTH)


def in_range(column: str, low=None, high=None) -> str:
    """CHECK body for a nullable column bounded on one or both sides."""
    bounds = []
    if low is not None:
        bounds.append(f"{column} >= {low}")
    if high is not None:
        bounds.append(f"{column} <= {high}")
    return f"{column} IS NULL OR ({' AND '.join(bounds)})"


def one_of(column: str, values: Iterable[str]) -> str:
    """CHECK body restricting a column to a fixed set of strings."""
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


def default(value: str) -> dict:
    """A string server default, quoted for SQL."""
    return {"server_default": text(f"'{value}'")}


def latitudine_column(description: str = "Latitudine in formato DD, es: 45.464200"):
    """A nullable decimal-degree latitude column, bounded by `limits.py`."""
    return Field(
        None,
        ge=LATITUDINE_MIN,
        le=LATITUDINE_MAX,
        sa_type=Numeric(9, 6),
        description=description,
    )


def longitudine_column(description: str = "Longitudine in formato DD, es: 9.190000"):
    """A nullable decimal-degree longitude column, bounded by `limits.py`."""
    return Field(
        None,
        ge=LONGITUDINE_MIN,
        le=LONGITUDINE_MAX,
        sa_type=Numeric(9, 6),
        description=description,
    )


def coordinate_checks(prefix: str = "") -> tuple[CheckConstraint, CheckConstraint]:
    """The CHECKs matching `latitudine_column` and `longitudine_column`."""
    return (
        CheckConstraint(
            in_range("latitudine", LATITUDINE_MIN, LATITUDINE_MAX),
            name=f"{prefix}valid_latitudine",
        ),
        CheckConstraint(
            in_range("longitudine", LONGITUDINE_MIN, LONGITUDINE_MAX),
            name=f"{prefix}valid_longitudine",
        ),
    )


# ============================================
# Autenticazione
# ============================================


def normalize_email(value: str) -> str:
    """Trim and lowercase an address, so stored and submitted values match."""
    return value.strip().lower()


# bcrypt hashes at most 72 bytes and silently ignores the rest, so a longer
# password protects an account no better than its first 72 bytes.
BCRYPT_MAX_BYTES = 72
PASSWORD_MIN_LENGTH = 8


def validate_password_length(value: str) -> str:
    """
    Reject a password bcrypt would silently truncate.

    The limit is in bytes, not characters: accented or emoji characters take
    several bytes each, so a 72-character password can still overflow it.
    """
    if len(value.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise ValueError(
            f"Password troppo lunga: massimo {BCRYPT_MAX_BYTES} byte "
            "(bcrypt ignora i caratteri successivi)"
        )
    return value


class UserLogin(BaseModel):
    """Dati per login utente"""

    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email_case(cls, v):
        """
        Normalize exactly like UserBase, but without rejecting a bad format:
        a malformed address must fail authentication (401), not validation (422).
        """
        return normalize_email(v)


class Token(BaseModel):
    """Token di accesso"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Dati contenuti nel token"""

    email: str | None = None
    id_utente: int | None = None
    ruolo: str | None = None


# ============================================
# Utenti
# ============================================


class UserBase(SQLModel):
    """Base utente"""

    email: str = Field(
        sa_type=String(255), unique=True
    )  # str, non EmailStr: domini .local
    nome: str = Field(sa_type=String(100))
    cognome: str = Field(sa_type=String(100))

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v):
        """Validazione email minimale: deve contenere @ e un dominio"""
        v = normalize_email(v)
        if "@" not in v:
            raise ValueError("Email non valida: manca @")
        local, _, domain = v.partition("@")
        if not local or not domain or "." not in domain:
            raise ValueError("Email non valida: formato scorretto")
        return v


class UserCreate(UserBase):
    """Creazione utente"""

    password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        description=f"Password (minimo {PASSWORD_MIN_LENGTH} caratteri, massimo {BCRYPT_MAX_BYTES} byte)",
    )
    ruolo: Ruolo = "user"

    @field_validator("password")
    @classmethod
    def check_password_length(cls, v):
        return validate_password_length(v)


class UserUpdate(BaseModel):
    """Aggiornamento utente"""

    email: str | None = None
    nome: str | None = None
    cognome: str | None = None
    ruolo: Ruolo | None = None
    attivo: bool | None = None


class UserResponse(UserBase):
    """Risposta con dati utente"""

    id_utente: int = Field(primary_key=True)
    ruolo: str = Field(sa_type=String(20), sa_column_kwargs=default("user"))
    data_creazione: datetime = Field(sa_column_kwargs=NOW)
    data_attivazione: datetime | None = None
    data_disattivazione: datetime | None = None
    ultimo_accesso: datetime | None = None
    attivo: bool = Field(sa_column_kwargs=TRUE)

    model_config = ConfigDict(from_attributes=True)


class Utente(UserResponse, table=True):
    __tablename__ = "utenti"
    __table_args__ = (
        CheckConstraint(one_of("ruolo", RUOLI), name="utenti_ruolo_check"),
        CheckConstraint(
            "data_disattivazione IS NULL OR data_disattivazione >= data_attivazione",
            name="valid_dates",
        ),
        {"comment": "Utenti del sistema con autenticazione"},
    )

    # Never part of a response: the reason the table extends UserResponse
    # rather than being it.
    password_hash: str = Field(sa_type=String(255))


class PasswordChange(BaseModel):
    """Cambio password"""

    new_password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        description=f"Nuova password (minimo {PASSWORD_MIN_LENGTH} caratteri, massimo {BCRYPT_MAX_BYTES} byte)",
    )
    current_password: str | None = None  # Richiesta solo per cambio proprio

    @field_validator("new_password")
    @classmethod
    def check_password_length(cls, v):
        return validate_password_length(v)


# ============================================
# Nodi
# ============================================


class NodoBase(SQLModel):
    """Base nodo"""

    id_nodo: str = Field(primary_key=True, sa_type=ID)
    nome_nodo: str | None = Field(None, sa_type=String(100))
    descrizione: str | None = Field(None, sa_type=Text)
    posizione: str | None = Field(None, sa_type=String(255))


class NodoCreate(NodoBase):
    """Creazione nodo"""

    configurazione: dict[str, Any] | None = None


class NodoResponse(NodoBase):
    """Risposta con dati nodo"""

    data_registrazione: datetime = Field(sa_column_kwargs=NOW)
    ultimo_messaggio: datetime | None = None
    # Null until an admin assigns the node; its hives follow its owner.
    id_proprietario: int | None = Field(
        None, foreign_key="utenti.id_utente", ondelete="SET NULL"
    )
    attivo: bool = Field(sa_column_kwargs=TRUE)
    configurazione: dict[str, Any] | None = Field(None, sa_type=JSONB)

    model_config = ConfigDict(from_attributes=True)


class NodoProprietarioUpdate(BaseModel):
    """Assign a node to a user, transfer it, or (null) unassign it."""

    id_utente: int | None


class Nodo(NodoResponse, table=True):
    __tablename__ = "nodi"
    __table_args__ = ({"comment": "Dispositivi IoT che trasmettono dati"},)


# ============================================
# Apiari
# ============================================


class ApiarioBase(SQLModel):
    """
    An apiary: the place a group of hives stands in, owned by one user.

    A hive is in exactly one apiary (`arnie.id_apiario`) and belongs to that
    apiary's owner. Sharing is granted per apiary (`utenti_apiari`).
    """

    nome_apiario: str = Field(sa_type=String(100))
    descrizione: str | None = Field(None, sa_type=Text)
    posizione: str | None = Field(None, sa_type=String(255))
    latitudine: Decimal | None = latitudine_column()
    longitudine: Decimal | None = longitudine_column()


class ApiarioCreate(ApiarioBase):
    """New apiary, owned by the caller."""

    metadati: dict[str, Any] | None = None


class ApiarioAdminCreate(ApiarioCreate):
    """New apiary created by an admin on behalf of a user."""

    id_utente_proprietario: int


class ApiarioUpdate(BaseModel):
    """
    Partial apiary update: an omitted or null field keeps its stored value.

    Neither the owner nor `predefinito` can change: the hives in an apiary
    belong to its owner, and every user keeps exactly one default.
    """

    nome_apiario: str | None = None
    descrizione: str | None = None
    posizione: str | None = None
    latitudine: Decimal | None = Field(
        None,
        ge=LATITUDINE_MIN,
        le=LATITUDINE_MAX,
        description="Latitudine in formato DD",
    )
    longitudine: Decimal | None = Field(
        None,
        ge=LONGITUDINE_MIN,
        le=LONGITUDINE_MAX,
        description="Longitudine in formato DD",
    )
    metadati: dict[str, Any] | None = None


class ApiarioResponse(ApiarioBase):
    """An apiary as the API returns it."""

    id_apiario: int = Field(primary_key=True)
    id_utente_proprietario: int = Field(
        foreign_key="utenti.id_utente", ondelete="CASCADE"
    )
    # The apiary a user starts with, where the hives of their newly assigned
    # nodes land. It cannot be deleted.
    predefinito: bool = Field(sa_column_kwargs=FALSE)
    data_creazione: datetime = Field(sa_column_kwargs=NOW)
    metadati: dict[str, Any] | None = Field(None, sa_type=JSONB)

    model_config = ConfigDict(from_attributes=True)


class ApiarioConAccesso(ApiarioResponse):
    """An apiary with what the caller may do on it."""

    # "owner", or the role the owner granted the caller; null for an admin
    # looking at someone else's apiary.
    accesso: str | None = None


class Apiario(ApiarioResponse, table=True):
    __tablename__ = "apiari"
    __table_args__ = (
        *coordinate_checks("apiari_"),
        {"comment": "Apiari: luoghi che raggruppano le arnie di un proprietario"},
    )


# ============================================
# Arnie
# ============================================


class ArniaBase(SQLModel):
    """Base arnia"""

    id_nodo: str = Field(sa_type=ID, foreign_key="nodi.id_nodo", ondelete="CASCADE")
    id_sensore_fisico: str = Field(sa_type=ID)
    nome_arnia: str | None = Field(None, sa_type=String(100))
    descrizione: str | None = Field(None, sa_type=Text)
    posizione: str | None = Field(None, sa_type=String(255))
    latitudine: Decimal | None = latitudine_column()
    longitudine: Decimal | None = longitudine_column()
    # The hive's owner is this apiary's owner. Null while its node is
    # unassigned; on creation, the node owner's default apiary.
    id_apiario: int | None = Field(None, foreign_key="apiari.id_apiario")


class ArniaCreate(ArniaBase):
    """Creazione arnia"""

    metadati: dict[str, Any] | None = None


class ArniaUpdate(BaseModel):
    """Aggiornamento arnia"""

    nome_arnia: str | None = None
    descrizione: str | None = None
    posizione: str | None = None
    latitudine: Decimal | None = Field(
        None,
        ge=LATITUDINE_MIN,
        le=LATITUDINE_MAX,
        description="Latitudine in formato DD",
    )
    longitudine: Decimal | None = Field(
        None,
        ge=LONGITUDINE_MIN,
        le=LONGITUDINE_MAX,
        description="Longitudine in formato DD",
    )
    attiva: bool | None = None
    metadati: dict[str, Any] | None = None


class ArniaResponse(ArniaBase):
    """Risposta con dati arnia"""

    id_arnia: int = Field(primary_key=True)
    data_installazione: datetime = Field(sa_column_kwargs=NOW)
    data_rimozione: datetime | None = None
    attiva: bool = Field(sa_column_kwargs=TRUE)
    metadati: dict[str, Any] | None = Field(None, sa_type=JSONB)

    model_config = ConfigDict(from_attributes=True)


class Arnia(ArniaResponse, table=True):
    __tablename__ = "arnie"
    __table_args__ = (
        UniqueConstraint(
            "id_nodo", "id_sensore_fisico", name="arnie_id_nodo_id_sensore_fisico_key"
        ),
        *coordinate_checks(),
        {"comment": "Arnie monitorate con sensori"},
    )


class ArniaApiarioUpdate(BaseModel):
    """Move a hive into another apiary of its owner."""

    id_apiario: int


class ArniaConStato(ArniaResponse):
    """Arnia con ultime letture e coordinate"""

    nome_apiario: str | None = None
    # "owner", or the role granted to the caller on the hive's apiary; null
    # when the caller has neither (an admin browsing every hive).
    accesso: str | None = None
    ultima_temperatura: Decimal | None = None
    ultima_umidita: Decimal | None = None
    ultimo_peso: Decimal | None = None
    ultima_batteria: Decimal | None = None
    ultimo_aggiornamento: datetime | None = None


# ============================================
# Letture
# ============================================


class LetturaBase(SQLModel):
    """Base lettura"""

    temperatura: Decimal | None = Field(None, sa_type=Numeric(5, 2))
    umidita: Decimal | None = Field(None, sa_type=Numeric(5, 2))
    peso: Decimal | None = Field(None, sa_type=Numeric(10, 3))
    # Node battery voltage; the payload key is `bat`.
    batteria: Decimal | None = Field(None, sa_type=Numeric(4, 3))

    @field_validator("temperatura")
    @classmethod
    def validate_temperatura(cls, v):
        if v is not None and (v < TEMPERATURA_MIN or v > TEMPERATURA_MAX):
            raise ValueError(
                f"Temperatura deve essere tra {TEMPERATURA_MIN} e {TEMPERATURA_MAX}°C"
            )
        return v

    @field_validator("umidita")
    @classmethod
    def validate_umidita(cls, v):
        if v is not None and (v < UMIDITA_MIN or v > UMIDITA_MAX):
            raise ValueError(f"Umidità deve essere tra {UMIDITA_MIN} e {UMIDITA_MAX}%")
        return v

    @field_validator("peso")
    @classmethod
    def validate_peso(cls, v):
        if v is not None and v < PESO_MIN:
            raise ValueError("Peso deve essere positivo")
        return v

    @field_validator("batteria")
    @classmethod
    def validate_batteria(cls, v):
        if v is not None and (v < BATTERIA_MIN or v > BATTERIA_MAX):
            raise ValueError(
                f"Batteria deve essere tra {BATTERIA_MIN} e {BATTERIA_MAX} V"
            )
        return v


class LetturaCreate(LetturaBase):
    """Creazione lettura"""

    id_arnia: int
    id_nodo: str
    timestamp: datetime | None = None
    dati_raw: dict[str, Any] | None = None


# The most ids one bulk delete takes: the readings listings' own `limit` cap,
# so every row a filtered listing shows can go in one request.
LETTURE_DELETE_MAX = 10000


class LettureDelete(BaseModel):
    """Readings to delete, by id."""

    id_letture: conlist(int, min_length=1, max_length=LETTURE_DELETE_MAX)


class LetturaResponse(LetturaBase):
    """Risposta con dati lettura"""

    id_lettura: int = Field(primary_key=True, sa_type=BigInteger)
    id_arnia: int = Field(foreign_key="arnie.id_arnia", ondelete="CASCADE")
    id_nodo: str = Field(sa_type=ID)
    timestamp: datetime = Field(sa_column_kwargs=NOW)
    dati_raw: dict[str, Any] | None = Field(None, sa_type=JSONB)

    model_config = ConfigDict(from_attributes=True)


class Lettura(LetturaResponse, table=True):
    __tablename__ = "letture"
    __table_args__ = (
        CheckConstraint(
            in_range("temperatura", TEMPERATURA_MIN, TEMPERATURA_MAX),
            name="valid_temperatura",
        ),
        CheckConstraint(
            in_range("umidita", UMIDITA_MIN, UMIDITA_MAX), name="valid_umidita"
        ),
        CheckConstraint(in_range("peso", PESO_MIN), name="valid_peso"),
        CheckConstraint(
            in_range("batteria", BATTERIA_MIN, BATTERIA_MAX), name="valid_batteria"
        ),
        {"comment": "Dati telemetrici dalle arnie"},
    )


class SerieTemperaturaResponse(BaseModel):
    """Risposta serie storica temperatura"""

    timestamp: datetime
    temperatura: Decimal

    model_config = ConfigDict(from_attributes=True)


class SerieUmiditaResponse(BaseModel):
    """Risposta serie storica umidita"""

    timestamp: datetime
    umidita: Decimal

    model_config = ConfigDict(from_attributes=True)


class SeriePesoResponse(BaseModel):
    """Risposta serie storica peso"""

    timestamp: datetime
    peso: Decimal

    model_config = ConfigDict(from_attributes=True)


class SerieBatteriaResponse(BaseModel):
    """Battery voltage time series."""

    timestamp: datetime
    batteria: Decimal

    model_config = ConfigDict(from_attributes=True)


class LettureQueryParams(BaseModel):
    """Parametri per query letture"""

    data_inizio: datetime | None = None
    data_fine: datetime | None = None
    limit: int = Field(default=1000, ge=1, le=10000)
    offset: int = Field(default=0, ge=0)


# ============================================
# Attività
# ============================================


class AttivitaBase(SQLModel):
    """Base attività"""

    tipo_attivita: TipoAttivita = Field(sa_type=String(50))
    descrizione: str | None = Field(None, sa_type=Text)
    dati: dict[str, Any] | None = Field(None, sa_type=JSONB)


class AttivitaCreate(AttivitaBase):
    """Creazione attività"""

    id_arnia: int
    timestamp: datetime | None = None


class AttivitaUpdate(BaseModel):
    """Aggiornamento attività"""

    tipo_attivita: TipoAttivita | None = None
    descrizione: str | None = None
    timestamp: datetime | None = None
    dati: dict[str, Any] | None = None


class AttivitaResponse(AttivitaBase):
    """Risposta con dati attività"""

    id_log: int = Field(primary_key=True, sa_type=BigInteger)
    # Nullable on purpose: ON DELETE SET NULL keeps the entry when the account goes.
    id_utente: int | None = Field(
        None, foreign_key="utenti.id_utente", ondelete="SET NULL"
    )
    id_arnia: int = Field(foreign_key="arnie.id_arnia", ondelete="CASCADE")
    timestamp: datetime = Field(sa_column_kwargs=NOW)

    model_config = ConfigDict(from_attributes=True)


class LogAttivita(AttivitaResponse, table=True):
    __tablename__ = "log_attivita"
    __table_args__ = (
        CheckConstraint(one_of("tipo_attivita", TIPI_ATTIVITA), name="valid_activity"),
        {"comment": "Registro interventi e attività degli apicoltori"},
    )


class AttivitaQueryParams(BaseModel):
    """Parametri per query attività"""

    data_inizio: datetime | None = None
    data_fine: datetime | None = None
    tipo_attivita: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


# ============================================
# Condivisione degli apiari
# ============================================


class CondivisioneCreate(BaseModel):
    """Share an apiary with a user, found by email."""

    email: str
    ruolo: RuoloApiario = "viewer"

    @field_validator("email")
    @classmethod
    def normalize_email_case(cls, v):
        return normalize_email(v)


class CondivisioneUpdate(BaseModel):
    """Change the role of an existing share."""

    ruolo: RuoloApiario


class CondivisioneBase(SQLModel):
    id_utente: int = Field(foreign_key="utenti.id_utente", ondelete="CASCADE")
    id_apiario: int = Field(foreign_key="apiari.id_apiario", ondelete="CASCADE")
    ruolo: str = Field(sa_type=String(20), sa_column_kwargs=default("viewer"))
    data_condivisione: datetime = Field(sa_column_kwargs=NOW)


class CondivisioneResponse(CondivisioneBase):
    """
    A share, with who it is for — identified only by the email the owner typed.

    No name or other profile field: any user can share their own apiary with
    any email, so this response must not tell them more about the account
    behind it than they already knew.
    """

    email: str


class UtenteApiario(CondivisioneBase, table=True):
    """
    A role granted on an apiary by its owner. Revoking deletes the row: a share
    has no history worth keeping, unlike readings or activities.
    """

    __tablename__ = "utenti_apiari"
    __table_args__ = (
        UniqueConstraint(
            "id_utente", "id_apiario", name="utenti_apiari_id_utente_id_apiario_key"
        ),
        CheckConstraint(
            one_of("ruolo", RUOLI_APIARIO), name="utenti_apiari_ruolo_check"
        ),
        {"comment": "Apiari condivisi dal proprietario con altri utenti"},
    )

    id: int | None = Field(default=None, primary_key=True)


# ============================================
# Token di sessione (no API shape)
# ============================================


class TokenSessione(SQLModel, table=True):
    """Unused on purpose: refresh tokens are stateless (#16). Kept for later."""

    __tablename__ = "token_sessione"

    id_token: int | None = Field(default=None, primary_key=True)
    id_utente: int | None = Field(
        default=None, foreign_key="utenti.id_utente", ondelete="CASCADE"
    )
    refresh_token: str = Field(sa_type=String(500), unique=True)
    data_creazione: datetime | None = Field(default=None, sa_column_kwargs=NOW)
    data_scadenza: datetime
    revocato: bool | None = Field(default=None, sa_column_kwargs=FALSE)
    ip_address: str | None = Field(default=None, sa_type=String(45))
    user_agent: str | None = Field(default=None, sa_type=Text)


# ============================================
# Risposte generiche
# ============================================


class MessageResponse(BaseModel):
    """Messaggio generico"""

    message: str
    detail: str | None = None


class ErrorResponse(BaseModel):
    """Risposta errore"""

    error: str
    detail: str | None = None
    code: int | None = None


# Indexes are declared after the classes so they can name real columns, sort
# order included. Names match the original init.sql.
INDEXES = (
    Index("idx_utenti_email", Utente.email),
    Index("idx_utenti_attivo", Utente.attivo),
    Index("idx_nodi_attivo", Nodo.attivo),
    Index("idx_nodi_ultimo_messaggio", Nodo.ultimo_messaggio),
    Index("idx_nodi_proprietario", Nodo.id_proprietario),
    Index("idx_arnie_nodo", Arnia.id_nodo),
    Index("idx_arnie_attiva", Arnia.attiva),
    Index("idx_arnie_apiario", Arnia.id_apiario),
    Index("idx_apiari_proprietario", Apiario.id_utente_proprietario),
    # One default apiary per user.
    Index(
        "uq_apiari_predefinito",
        Apiario.id_utente_proprietario,
        unique=True,
        postgresql_where=Apiario.predefinito,
    ),
    Index("idx_utenti_apiari_utente", UtenteApiario.id_utente),
    Index("idx_utenti_apiari_apiario", UtenteApiario.id_apiario),
    Index("idx_letture_arnia", Lettura.id_arnia),
    Index("idx_letture_timestamp", Lettura.timestamp.desc()),
    Index("idx_letture_arnia_timestamp", Lettura.id_arnia, Lettura.timestamp.desc()),
    Index("idx_letture_nodo", Lettura.id_nodo),
    Index("idx_log_utente", LogAttivita.id_utente),
    Index("idx_log_arnia", LogAttivita.id_arnia),
    Index("idx_log_timestamp", LogAttivita.timestamp.desc()),
    Index("idx_log_tipo", LogAttivita.tipo_attivita),
    Index("idx_token_utente", TokenSessione.id_utente),
    Index("idx_token_scadenza", TokenSessione.data_scadenza),
    Index("idx_token_revocato", TokenSessione.revocato),
)

metadata = SQLModel.metadata
