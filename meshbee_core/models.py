"""
The database schema, as SQLModel table classes.

This module is the schema's single source: Alembic autogenerates migrations by
diffing `SQLModel.metadata` against the database, and
`tests/integration/test_migrations.py` asserts that the migration chain and
these classes produce the same catalog — CHECK constraints included, which
autogenerate does not compare.

Bounds and value sets come from `limits.py`. Constraint and index names are
spelled out so that they match the ones Postgres generated for the original
`init.sql`; a live install must not see them renamed.

Defaults are `server_default`s for now, to keep the DDL identical to the
baseline revision. Decimal precision is given as `sa_type=Numeric(p, s)`
rather than `max_digits`/`decimal_places`: pydantic 2.5 rejects those on an
Optional[Decimal].
"""
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import BigInteger, CheckConstraint, Index, Numeric, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from meshbee_core.limits import (
    BATTERIA_MAX, BATTERIA_MIN, ID_MAX_LENGTH, LATITUDINE_MAX, LATITUDINE_MIN,
    LONGITUDINE_MAX, LONGITUDINE_MIN, PERMESSI, PESO_MIN, RUOLI, TEMPERATURA_MAX,
    TEMPERATURA_MIN, TIPI_ATTIVITA, UMIDITA_MAX, UMIDITA_MIN,
)

NOW = {"server_default": text("CURRENT_TIMESTAMP")}
TRUE = {"server_default": text("true")}
FALSE = {"server_default": text("false")}


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


class Utente(SQLModel, table=True):
    __tablename__ = "utenti"
    __table_args__ = (
        CheckConstraint(one_of("ruolo", RUOLI), name="utenti_ruolo_check"),
        CheckConstraint(
            "data_disattivazione IS NULL OR data_disattivazione >= data_attivazione",
            name="valid_dates",
        ),
        {"comment": "Utenti del sistema con autenticazione"},
    )

    id_utente: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(max_length=255, unique=True)
    password_hash: str = Field(max_length=255)
    nome: str = Field(max_length=100)
    cognome: str = Field(max_length=100)
    ruolo: Optional[str] = Field(default=None, max_length=20, sa_column_kwargs=default("user"))
    data_creazione: Optional[datetime] = Field(default=None, sa_column_kwargs=NOW)
    data_attivazione: Optional[datetime] = None
    data_disattivazione: Optional[datetime] = None
    ultimo_accesso: Optional[datetime] = None
    attivo: Optional[bool] = Field(default=None, sa_column_kwargs=TRUE)


class Nodo(SQLModel, table=True):
    __tablename__ = "nodi"
    __table_args__ = ({"comment": "Dispositivi IoT che trasmettono dati"},)

    id_nodo: str = Field(primary_key=True, max_length=ID_MAX_LENGTH)
    nome_nodo: Optional[str] = Field(default=None, max_length=100)
    descrizione: Optional[str] = Field(default=None, sa_type=Text)
    posizione: Optional[str] = Field(default=None, max_length=255)
    data_registrazione: Optional[datetime] = Field(default=None, sa_column_kwargs=NOW)
    ultimo_messaggio: Optional[datetime] = None
    attivo: Optional[bool] = Field(default=None, sa_column_kwargs=TRUE)
    configurazione: Optional[dict] = Field(default=None, sa_type=JSONB)


class Arnia(SQLModel, table=True):
    __tablename__ = "arnie"
    __table_args__ = (
        UniqueConstraint("id_nodo", "id_sensore_fisico", name="arnie_id_nodo_id_sensore_fisico_key"),
        CheckConstraint(
            in_range("latitudine", LATITUDINE_MIN, LATITUDINE_MAX), name="valid_latitudine"
        ),
        CheckConstraint(
            in_range("longitudine", LONGITUDINE_MIN, LONGITUDINE_MAX), name="valid_longitudine"
        ),
        {"comment": "Arnie monitorate con sensori"},
    )

    id_arnia: Optional[int] = Field(default=None, primary_key=True)
    id_nodo: Optional[str] = Field(
        default=None, max_length=ID_MAX_LENGTH, foreign_key="nodi.id_nodo", ondelete="CASCADE"
    )
    id_sensore_fisico: str = Field(max_length=ID_MAX_LENGTH)
    nome_arnia: Optional[str] = Field(default=None, max_length=100)
    descrizione: Optional[str] = Field(default=None, sa_type=Text)
    posizione: Optional[str] = Field(default=None, max_length=255)
    latitudine: Optional[Decimal] = Field(default=None, sa_type=Numeric(9, 6))
    longitudine: Optional[Decimal] = Field(default=None, sa_type=Numeric(9, 6))
    data_installazione: Optional[datetime] = Field(default=None, sa_column_kwargs=NOW)
    data_rimozione: Optional[datetime] = None
    attiva: Optional[bool] = Field(default=None, sa_column_kwargs=TRUE)
    metadati: Optional[dict] = Field(default=None, sa_type=JSONB)


class UtenteArnia(SQLModel, table=True):
    __tablename__ = "utenti_arnie"
    __table_args__ = (
        UniqueConstraint("id_utente", "id_arnia", name="utenti_arnie_id_utente_id_arnia_key"),
        CheckConstraint(one_of("permessi", PERMESSI), name="utenti_arnie_permessi_check"),
        CheckConstraint(
            "data_disassociazione IS NULL OR data_disassociazione >= data_associazione",
            name="valid_association_dates",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    id_utente: Optional[int] = Field(
        default=None, foreign_key="utenti.id_utente", ondelete="CASCADE"
    )
    id_arnia: Optional[int] = Field(
        default=None, foreign_key="arnie.id_arnia", ondelete="CASCADE"
    )
    data_associazione: Optional[datetime] = Field(default=None, sa_column_kwargs=NOW)
    data_disassociazione: Optional[datetime] = None
    permessi: Optional[str] = Field(default=None, max_length=20, sa_column_kwargs=default("read"))
    attivo: Optional[bool] = Field(default=None, sa_column_kwargs=TRUE)


class Lettura(SQLModel, table=True):
    __tablename__ = "letture"
    __table_args__ = (
        CheckConstraint(
            in_range("temperatura", TEMPERATURA_MIN, TEMPERATURA_MAX), name="valid_temperatura"
        ),
        CheckConstraint(in_range("umidita", UMIDITA_MIN, UMIDITA_MAX), name="valid_umidita"),
        CheckConstraint(in_range("peso", PESO_MIN), name="valid_peso"),
        CheckConstraint(
            in_range("batteria", BATTERIA_MIN, BATTERIA_MAX), name="valid_batteria"
        ),
        {"comment": "Dati telemetrici dalle arnie"},
    )

    id_lettura: Optional[int] = Field(default=None, primary_key=True, sa_type=BigInteger)
    id_arnia: Optional[int] = Field(
        default=None, foreign_key="arnie.id_arnia", ondelete="CASCADE"
    )
    id_nodo: str = Field(max_length=ID_MAX_LENGTH)
    timestamp: datetime = Field(sa_column_kwargs=NOW)
    temperatura: Optional[Decimal] = Field(default=None, sa_type=Numeric(5, 2))
    umidita: Optional[Decimal] = Field(default=None, sa_type=Numeric(5, 2))
    peso: Optional[Decimal] = Field(default=None, sa_type=Numeric(10, 3))
    # Node battery voltage; the payload key is `bat`.
    batteria: Optional[Decimal] = Field(default=None, sa_type=Numeric(4, 3))
    dati_raw: Optional[dict] = Field(default=None, sa_type=JSONB)


class LogAttivita(SQLModel, table=True):
    __tablename__ = "log_attivita"
    __table_args__ = (
        CheckConstraint(one_of("tipo_attivita", TIPI_ATTIVITA), name="valid_activity"),
        {"comment": "Registro interventi e attività degli apicoltori"},
    )

    id_log: Optional[int] = Field(default=None, primary_key=True, sa_type=BigInteger)
    id_utente: Optional[int] = Field(
        default=None, foreign_key="utenti.id_utente", ondelete="SET NULL"
    )
    id_arnia: Optional[int] = Field(
        default=None, foreign_key="arnie.id_arnia", ondelete="CASCADE"
    )
    timestamp: Optional[datetime] = Field(default=None, sa_column_kwargs=NOW)
    tipo_attivita: str = Field(max_length=50)
    descrizione: Optional[str] = Field(default=None, sa_type=Text)
    dati: Optional[dict] = Field(default=None, sa_type=JSONB)


class TokenSessione(SQLModel, table=True):
    """Unused on purpose: refresh tokens are stateless (#16). Kept for later."""
    __tablename__ = "token_sessione"

    id_token: Optional[int] = Field(default=None, primary_key=True)
    id_utente: Optional[int] = Field(
        default=None, foreign_key="utenti.id_utente", ondelete="CASCADE"
    )
    refresh_token: str = Field(max_length=500, unique=True)
    data_creazione: Optional[datetime] = Field(default=None, sa_column_kwargs=NOW)
    data_scadenza: datetime
    revocato: Optional[bool] = Field(default=None, sa_column_kwargs=FALSE)
    ip_address: Optional[str] = Field(default=None, max_length=45)
    user_agent: Optional[str] = Field(default=None, sa_type=Text)


# Indexes are declared after the classes so they can name real columns, sort
# order included. Names match the original init.sql.
INDEXES = (
    Index("idx_utenti_email", Utente.email),
    Index("idx_utenti_attivo", Utente.attivo),
    Index("idx_nodi_attivo", Nodo.attivo),
    Index("idx_nodi_ultimo_messaggio", Nodo.ultimo_messaggio),
    Index("idx_arnie_nodo", Arnia.id_nodo),
    Index("idx_arnie_attiva", Arnia.attiva),
    Index("idx_utenti_arnie_utente", UtenteArnia.id_utente),
    Index("idx_utenti_arnie_arnia", UtenteArnia.id_arnia),
    Index("idx_utenti_arnie_attivo", UtenteArnia.attivo),
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
