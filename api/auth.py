"""
Autenticazione e gestione JWT
"""
from datetime import datetime, timedelta
from typing import Optional, Dict
from jose import JWTError, jwt
import bcrypt
import psycopg2
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import logging

from api.config import settings
from api.database import get_db_cursor
from api.models import Permesso, TokenData, UserResponse

logger = logging.getLogger(__name__)

# Livelli di permesso (admin > write > read).
# Keys must match the Permesso literal, and therefore the CHECK constraint on
# utenti_arnie.permessi — tests/integration/test_models.py asserts it.
PERMISSION_LEVELS = {"read": 1, "write": 2, "admin": 3}

# Security scheme.
# auto_error=False so a missing or malformed Authorization header reaches
# get_current_user, which answers 401 with a WWW-Authenticate header. Left to
# itself HTTPBearer raises a bare 403, which tells a client it is forbidden
# rather than that it needs to authenticate.
security = HTTPBearer(auto_error=False)


def database_unavailable_error(exc: Exception) -> HTTPException:
    """
    Translate a database failure into 503 rather than an authentication verdict.

    A connection problem must not be reported as wrong credentials or a missing
    permission: clients would log the user out and retry the login, hammering the
    database exactly when it is already struggling.
    """
    logger.error(f"Database non raggiungibile: {exc}")
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Servizio temporaneamente non disponibile",
    )


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica una password contro il suo hash bcrypt"""
    try:
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )
    except Exception as e:
        logger.error(f"Errore verifica password: {e}")
        return False


def get_password_hash(password: str) -> str:
    """Genera hash bcrypt di una password"""
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=12))
    return hashed.decode('utf-8')


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Crea un JWT access token
    
    Args:
        data: Dati da includere nel token
        expires_delta: Durata del token (default: da config)
    
    Returns:
        Token JWT
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY.get_secret_value(), algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict) -> str:
    """
    Crea un JWT refresh token
    
    Args:
        data: Dati da includere nel token
    
    Returns:
        Refresh token JWT
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY.get_secret_value(), algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> Dict:
    """
    Decodifica un JWT token
    
    Args:
        token: Token JWT
    
    Returns:
        Payload del token
    
    Raises:
        JWTError: Se il token non è valido
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY.get_secret_value(), algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError as e:
        logger.error(f"Errore decodifica token: {e}")
        raise


def authenticate_user(email: str, password: str) -> Optional[Dict]:
    """
    Autentica un utente
    
    Args:
        email: Email dell'utente
        password: Password in chiaro
    
    Returns:
        Dati utente se autenticazione riuscita, None altrimenti
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """
                SELECT id_utente, email, password_hash, nome, cognome, ruolo, attivo
                FROM utenti
                WHERE email = %s
                """,
                (email,)
            )
            user = cursor.fetchone()
            
            if not user:
                return None
            
            if not user['attivo']:
                return None
            
            if not verify_password(password, user['password_hash']):
                return None
            
            # Aggiorna ultimo accesso
            cursor.execute(
                """
                UPDATE utenti 
                SET ultimo_accesso = CURRENT_TIMESTAMP 
                WHERE id_utente = %s
                """,
                (user['id_utente'],)
            )
            
            return user
    except psycopg2.Error as e:
        raise database_unavailable_error(e)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Dict:
    """
    Dependency per ottenere l'utente corrente dal token JWT
    
    Args:
        credentials: Credenziali HTTP Bearer
    
    Returns:
        Dati dell'utente corrente
    
    Raises:
        HTTPException: Se il token non è valido o l'utente non esiste
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenziali non valide",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # auto_error=False: no header, or one that is not a Bearer token.
    if credentials is None:
        raise credentials_exception

    try:
        token = credentials.credentials
        payload = decode_token(token)
        
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
        
        # Verifica che sia un access token
        if payload.get("type") != "access":
            raise credentials_exception
        
        token_data = TokenData(email=email)
        
    except JWTError:
        raise credentials_exception
    
    # Recupera utente dal database
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """
                SELECT id_utente, email, nome, cognome, ruolo, attivo,
                       data_creazione, data_attivazione, data_disattivazione, ultimo_accesso
                FROM utenti
                WHERE email = %s
                """,
                (token_data.email,)
            )
            user = cursor.fetchone()
            
            if user is None or not user['attivo']:
                raise credentials_exception

            return dict(user)
    except HTTPException:
        raise
    except psycopg2.Error as e:
        raise database_unavailable_error(e)


async def get_current_active_user(current_user: Dict = Depends(get_current_user)) -> Dict:
    """
    Dependency per verificare che l'utente sia attivo
    
    Args:
        current_user: Utente corrente
    
    Returns:
        Dati dell'utente se attivo
    
    Raises:
        HTTPException: Se l'utente non è attivo
    """
    if not current_user.get('attivo'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Utente non attivo"
        )
    return current_user


async def get_current_admin_user(current_user: Dict = Depends(get_current_active_user)) -> Dict:
    """
    Dependency per verificare che l'utente sia admin
    
    Args:
        current_user: Utente corrente
    
    Returns:
        Dati dell'utente se admin
    
    Raises:
        HTTPException: Se l'utente non è admin
    """
    if current_user.get('ruolo') != 'admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permessi insufficienti - richiesto ruolo admin"
        )
    return current_user


def check_user_arnia_access(
    id_utente: int, id_arnia: int, required_permission: Permesso = "read"
) -> bool:
    """
    Verifica se un utente ha accesso a un'arnia

    Args:
        id_utente: ID dell'utente
        id_arnia: ID dell'arnia
        required_permission: Permesso richiesto (read, write, admin)

    Returns:
        True se l'utente ha accesso, False altrimenti

    Raises:
        ValueError: Se required_permission non è un permesso conosciuto
    """
    # Fail closed and loudly on an unknown requirement. Defaulting it to level 0
    # would make `user_level >= 0` true for everyone, silently granting access.
    if required_permission not in PERMISSION_LEVELS:
        raise ValueError(f"Permesso richiesto sconosciuto: {required_permission!r}")

    try:
        with get_db_cursor() as cursor:
            # Prima verifica se l'utente è admin
            cursor.execute(
                "SELECT ruolo FROM utenti WHERE id_utente = %s",
                (id_utente,)
            )
            user = cursor.fetchone()
            if user and user['ruolo'] == 'admin':
                return True
            
            # Altrimenti verifica l'associazione
            cursor.execute(
                """
                SELECT permessi FROM utenti_arnie
                WHERE id_utente = %s AND id_arnia = %s AND attivo = true
                """,
                (id_utente, id_arnia)
            )
            result = cursor.fetchone()
            
            if not result:
                return False

            # `permessi` is constrained by a CHECK in init.sql to exactly these
            # keys, so index directly instead of masking an unexpected value.
            return PERMISSION_LEVELS[result['permessi']] >= PERMISSION_LEVELS[required_permission]
    except psycopg2.Error as e:
        raise database_unavailable_error(e)
