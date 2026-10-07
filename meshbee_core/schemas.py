"""
Modelli Pydantic per validazione e serializzazione
"""
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from decimal import Decimal

from meshbee_core.limits import (
    BATTERIA_MAX, BATTERIA_MIN, LATITUDINE_MAX, LATITUDINE_MIN, LONGITUDINE_MAX,
    LONGITUDINE_MIN, PESO_MIN, TEMPERATURA_MAX, TEMPERATURA_MIN, UMIDITA_MAX,
    UMIDITA_MIN,
    # Re-exported: the value sets are part of this module's public surface.
    Permesso, Ruolo, TipoAttivita,
)

# The bounds and value sets live in meshbee_core.limits, which the table models
# also build their CHECK constraints from. Declaring them on the schemas turns a
# violation into a 422 at the edge instead of a 500 from the driver, and
# documents the options in the OpenAPI schema.


# ============================================
# Modelli Autenticazione
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

    @field_validator('email')
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
    email: Optional[str] = None
    id_utente: Optional[int] = None
    ruolo: Optional[str] = None


# ============================================
# Modelli Utente
# ============================================

class UserBase(BaseModel):
    """Base utente"""
    email: str  # str invece di EmailStr per supportare domini .local e interni
    nome: str
    cognome: str

    @field_validator('email')
    @classmethod
    def validate_email_format(cls, v):
        """Validazione email minimale: deve contenere @ e un dominio"""
        v = normalize_email(v)
        if '@' not in v:
            raise ValueError('Email non valida: manca @')
        local, _, domain = v.partition('@')
        if not local or not domain or '.' not in domain:
            raise ValueError('Email non valida: formato scorretto')
        return v


class UserCreate(UserBase):
    """Creazione utente"""
    password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        description=f"Password (minimo {PASSWORD_MIN_LENGTH} caratteri, massimo {BCRYPT_MAX_BYTES} byte)"
    )
    ruolo: Ruolo = "user"

    @field_validator('password')
    @classmethod
    def check_password_length(cls, v):
        return validate_password_length(v)


class UserUpdate(BaseModel):
    """Aggiornamento utente"""
    email: Optional[str] = None
    nome: Optional[str] = None
    cognome: Optional[str] = None
    ruolo: Optional[Ruolo] = None
    attivo: Optional[bool] = None


class UserResponse(UserBase):
    """Risposta con dati utente"""
    id_utente: int
    ruolo: str
    data_creazione: datetime
    data_attivazione: Optional[datetime] = None
    data_disattivazione: Optional[datetime] = None
    ultimo_accesso: Optional[datetime] = None
    attivo: bool
    
    model_config = ConfigDict(from_attributes=True)


# ============================================
# Modelli Nodo
# ============================================

class NodoBase(BaseModel):
    """Base nodo"""
    id_nodo: str
    nome_nodo: Optional[str] = None
    descrizione: Optional[str] = None
    posizione: Optional[str] = None


class NodoCreate(NodoBase):
    """Creazione nodo"""
    configurazione: Optional[Dict[str, Any]] = None


class NodoResponse(NodoBase):
    """Risposta con dati nodo"""
    data_registrazione: datetime
    ultimo_messaggio: Optional[datetime] = None
    attivo: bool
    configurazione: Optional[Dict[str, Any]] = None
    
    model_config = ConfigDict(from_attributes=True)


# ============================================
# Modelli Arnia
# ============================================

class ArniaBase(BaseModel):
    """Base arnia"""
    id_nodo: str
    id_sensore_fisico: str
    nome_arnia: Optional[str] = None
    descrizione: Optional[str] = None
    posizione: Optional[str] = None
    latitudine: Optional[Decimal] = Field(None, ge=LATITUDINE_MIN, le=LATITUDINE_MAX, description="Latitudine in formato DD, es: 45.464200")
    longitudine: Optional[Decimal] = Field(None, ge=LONGITUDINE_MIN, le=LONGITUDINE_MAX, description="Longitudine in formato DD, es: 9.190000")


class ArniaCreate(ArniaBase):
    """Creazione arnia"""
    metadati: Optional[Dict[str, Any]] = None


class ArniaUpdate(BaseModel):
    """Aggiornamento arnia"""
    nome_arnia: Optional[str] = None
    descrizione: Optional[str] = None
    posizione: Optional[str] = None
    latitudine: Optional[Decimal] = Field(None, ge=LATITUDINE_MIN, le=LATITUDINE_MAX, description="Latitudine in formato DD")
    longitudine: Optional[Decimal] = Field(None, ge=LONGITUDINE_MIN, le=LONGITUDINE_MAX, description="Longitudine in formato DD")
    attiva: Optional[bool] = None
    metadati: Optional[Dict[str, Any]] = None


class ArniaResponse(ArniaBase):
    """Risposta con dati arnia"""
    id_arnia: int
    data_installazione: datetime
    data_rimozione: Optional[datetime] = None
    attiva: bool
    metadati: Optional[Dict[str, Any]] = None
    latitudine: Optional[Decimal] = None
    longitudine: Optional[Decimal] = None

    model_config = ConfigDict(from_attributes=True)


class ArniaConStato(ArniaResponse):
    """Arnia con ultime letture e coordinate"""
    ultima_temperatura: Optional[Decimal] = None
    ultima_umidita: Optional[Decimal] = None
    ultimo_peso: Optional[Decimal] = None
    ultima_batteria: Optional[Decimal] = None
    ultimo_aggiornamento: Optional[datetime] = None
    latitudine: Optional[Decimal] = None
    longitudine: Optional[Decimal] = None


# ============================================
# Modelli Lettura
# ============================================

class LetturaBase(BaseModel):
    """Base lettura"""
    temperatura: Optional[Decimal] = None
    umidita: Optional[Decimal] = None
    peso: Optional[Decimal] = None
    batteria: Optional[Decimal] = None
    
    @field_validator('temperatura')
    @classmethod
    def validate_temperatura(cls, v):
        if v is not None and (v < TEMPERATURA_MIN or v > TEMPERATURA_MAX):
            raise ValueError(f'Temperatura deve essere tra {TEMPERATURA_MIN} e {TEMPERATURA_MAX}°C')
        return v
    
    @field_validator('umidita')
    @classmethod
    def validate_umidita(cls, v):
        if v is not None and (v < UMIDITA_MIN or v > UMIDITA_MAX):
            raise ValueError(f'Umidità deve essere tra {UMIDITA_MIN} e {UMIDITA_MAX}%')
        return v
    
    @field_validator('peso')
    @classmethod
    def validate_peso(cls, v):
        if v is not None and v < PESO_MIN:
            raise ValueError('Peso deve essere positivo')
        return v

    @field_validator('batteria')
    @classmethod
    def validate_batteria(cls, v):
        if v is not None and (v < BATTERIA_MIN or v > BATTERIA_MAX):
            raise ValueError(f'Batteria deve essere tra {BATTERIA_MIN} e {BATTERIA_MAX} V')
        return v


class LetturaCreate(LetturaBase):
    """Creazione lettura"""
    id_arnia: int
    id_nodo: str
    timestamp: Optional[datetime] = None
    dati_raw: Optional[Dict[str, Any]] = None


class LetturaResponse(LetturaBase):
    """Risposta con dati lettura"""
    id_lettura: int
    id_arnia: int
    id_nodo: str
    timestamp: datetime
    dati_raw: Optional[Dict[str, Any]] = None
    
    model_config = ConfigDict(from_attributes=True)


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


# ============================================
# Modelli Attività
# ============================================

class AttivitaBase(BaseModel):
    """Base attività"""
    tipo_attivita: TipoAttivita
    descrizione: Optional[str] = None
    dati: Optional[Dict[str, Any]] = None


class AttivitaCreate(AttivitaBase):
    """Creazione attività"""
    id_arnia: int
    timestamp: Optional[datetime] = None


class AttivitaUpdate(BaseModel):
    """Aggiornamento attività"""
    tipo_attivita: Optional[TipoAttivita] = None
    descrizione: Optional[str] = None
    timestamp: Optional[datetime] = None
    dati: Optional[Dict[str, Any]] = None


class AttivitaResponse(AttivitaBase):
    """Risposta con dati attività"""
    id_log: int
    id_utente: Optional[int] = None
    id_arnia: int
    timestamp: datetime
    
    model_config = ConfigDict(from_attributes=True)


# ============================================
# Modelli Associazione Utente-Arnia
# ============================================

class UtenteArniaCreate(BaseModel):
    """Associazione utente-arnia"""
    id_utente: int
    id_arnia: int
    permessi: Permesso = "read"


class UtenteArniaResponse(BaseModel):
    """Risposta associazione"""
    id: int
    id_utente: int
    id_arnia: int
    data_associazione: datetime
    data_disassociazione: Optional[datetime] = None
    permessi: str
    attivo: bool
    
    model_config = ConfigDict(from_attributes=True)


# ============================================
# Modelli Response Generici
# ============================================

class MessageResponse(BaseModel):
    """Messaggio generico"""
    message: str
    detail: Optional[str] = None


class ErrorResponse(BaseModel):
    """Risposta errore"""
    error: str
    detail: Optional[str] = None
    code: Optional[int] = None



# ============================================
# Modelli Password
# ============================================

class PasswordChange(BaseModel):
    """Cambio password"""
    new_password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        description=f"Nuova password (minimo {PASSWORD_MIN_LENGTH} caratteri, massimo {BCRYPT_MAX_BYTES} byte)"
    )
    current_password: Optional[str] = None  # Richiesta solo per cambio proprio

    @field_validator('new_password')
    @classmethod
    def check_password_length(cls, v):
        return validate_password_length(v)


# ============================================
# Query Parameters
# ============================================

class LettureQueryParams(BaseModel):
    """Parametri per query letture"""
    data_inizio: Optional[datetime] = None
    data_fine: Optional[datetime] = None
    limit: int = Field(default=1000, ge=1, le=10000)
    offset: int = Field(default=0, ge=0)


class AttivitaQueryParams(BaseModel):
    """Parametri per query attività"""
    data_inizio: Optional[datetime] = None
    data_fine: Optional[datetime] = None
    tipo_attivita: Optional[str] = None
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
