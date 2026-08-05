"""
Beehive IoT API - Applicazione principale

Thin HTTP layer: each handler validates its input, opens a cursor, calls one
service in `meshbee_core`, and returns the result. There is no SQL here — see
README.md for where new code belongs.
"""
from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager, contextmanager
from typing import List, Optional, Dict
from datetime import datetime
import logging

from api.config import settings
from api.auth import (
    authenticate_user, create_access_token, create_refresh_token,
    get_current_active_user, get_current_admin_user,
    check_user_arnia_access
)
from meshbee_core.db import init_db_pool, close_db_pool, get_db_cursor, ping
from meshbee_core.errors import Conflict, InvalidData, NotFound
from meshbee_core.services import (
    accessi as accessi_service,
    arnie as arnie_service,
    attivita as attivita_service,
    letture as letture_service,
    nodi as nodi_service,
    utenti as utenti_service,
)
from meshbee_core.schemas import (
    UserLogin, Token, UserCreate, UserResponse, UserUpdate,
    NodoCreate, NodoResponse, ArniaCreate, ArniaResponse, ArniaUpdate, ArniaConStato,
    LetturaCreate, LetturaResponse, AttivitaCreate, AttivitaUpdate, AttivitaResponse,
    SerieTemperaturaResponse, SerieUmiditaResponse, SeriePesoResponse,
    UtenteArniaCreate, PasswordChange, MessageResponse, ErrorResponse
)

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Lifecycle management
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestione startup e shutdown dell'applicazione"""
    # Startup
    logger.info("Avvio applicazione...")
    init_db_pool(settings)
    yield
    # Shutdown
    logger.info("Chiusura applicazione...")
    close_db_pool()


# Creazione app FastAPI
app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    description=settings.API_DESCRIPTION,
    lifespan=lifespan
)

# Configurazione CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================
# TRADUZIONE ERRORI
# ============================================

# What a service outcome means over HTTP. The services themselves know nothing
# about status codes; this is the only place the two vocabularies meet.
ERROR_STATUS = {
    NotFound: status.HTTP_404_NOT_FOUND,
    Conflict: status.HTTP_409_CONFLICT,
    InvalidData: status.HTTP_400_BAD_REQUEST,
}


@contextmanager
def db_operation(descrizione: str):
    """
    Open a cursor and turn a failed service call into the right status code.

    `descrizione` only ever reaches the log line for an unexpected failure —
    the response for those stays deliberately vague, since the exception text
    may name tables or columns.
    """
    try:
        with get_db_cursor() as cursor:
            yield cursor
    except HTTPException:
        raise
    except tuple(ERROR_STATUS) as e:
        raise HTTPException(status_code=ERROR_STATUS[type(e)], detail=str(e))
    except Exception as e:
        logger.error(f"Errore {descrizione}: {e}")
        raise HTTPException(status_code=500, detail="Errore interno del server")


def require_arnia_access(current_user: Dict, id_arnia: int, permesso: str, detail: str):
    """Guard an arnia-scoped endpoint, answering 403 when the user is not allowed."""
    if not check_user_arnia_access(current_user['id_utente'], id_arnia, permesso):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


# ============================================
# ENDPOINT AUTENTICAZIONE
# ============================================

@app.post("/api/auth/login", response_model=Token, tags=["Autenticazione"])
async def login(user_login: UserLogin):
    """
    Login utente e generazione token JWT

    Returns:
        Access token e refresh token
    """
    user = authenticate_user(user_login.email, user_login.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o password non corretti",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Crea token
    access_token = create_access_token(data={"sub": user['email']})
    refresh_token = create_refresh_token(data={"sub": user['email']})

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }


@app.get("/api/auth/me", response_model=UserResponse, tags=["Autenticazione"])
async def get_me(current_user: dict = Depends(get_current_active_user)):
    """
    Ottieni informazioni sull'utente corrente

    Returns:
        Dati dell'utente autenticato
    """
    return current_user


# ============================================
# ENDPOINT UTENTE (User APIs)
# ============================================

@app.get("/api/user/arnie", response_model=List[ArniaConStato], tags=["Utente"])
async def get_user_arnie(current_user: dict = Depends(get_current_active_user)):
    """
    Ottieni lista delle arnie associate all'utente con lo stato attuale

    Returns:
        Lista di arnie con ultime letture
    """
    with db_operation("recupero arnie utente") as cursor:
        return arnie_service.list_for_utente(cursor, current_user)


@app.get("/api/user/arnie/{id_arnia}/letture", response_model=List[LetturaResponse], tags=["Utente"])
async def get_user_letture(
    id_arnia: int,
    data_inizio: Optional[datetime] = Query(None, description="Data inizio (default: 1 anno fa)"),
    data_fine: Optional[datetime] = Query(None, description="Data fine (default: ora)"),
    limit: int = Query(1000, ge=1, le=10000, description="Numero massimo di letture"),
    current_user: dict = Depends(get_current_active_user)
):
    """
    Ottieni letture di un'arnia

    Args:
        id_arnia: ID dell'arnia
        data_inizio: Data inizio periodo (opzionale)
        data_fine: Data fine periodo (opzionale)
        limit: Numero massimo di risultati

    Returns:
        Lista di letture ordinate per timestamp (più recente prima)
    """
    require_arnia_access(current_user, id_arnia, "read", "Non hai accesso a questa arnia")

    with db_operation("recupero letture") as cursor:
        return letture_service.list_for_arnia(cursor, id_arnia, data_inizio, data_fine, limit)


@app.get("/api/user/arnie/{id_arnia}/attivita", response_model=List[AttivitaResponse], tags=["Utente"])
async def get_user_attivita(
    id_arnia: int,
    data_inizio: Optional[datetime] = Query(None, description="Data inizio (default: 1 anno fa)"),
    data_fine: Optional[datetime] = Query(None, description="Data fine (default: ora)"),
    tipo_attivita: Optional[str] = Query(None, description="Filtra per tipo attività"),
    limit: int = Query(100, ge=1, le=1000, description="Numero massimo di attività"),
    current_user: dict = Depends(get_current_active_user)
):
    """
    Ottieni log attività di un'arnia

    Args:
        id_arnia: ID dell'arnia
        data_inizio: Data inizio periodo (opzionale)
        data_fine: Data fine periodo (opzionale)
        tipo_attivita: Tipo di attività (opzionale)
        limit: Numero massimo di risultati

    Returns:
        Lista di attività ordinate per timestamp (più recente prima)
    """
    require_arnia_access(current_user, id_arnia, "read", "Non hai accesso a questa arnia")

    with db_operation("recupero attività") as cursor:
        return attivita_service.list_for_arnia(
            cursor, id_arnia, data_inizio, data_fine, limit, tipo_attivita
        )


@app.post("/api/user/arnie/{id_arnia}/attivita", response_model=AttivitaResponse, tags=["Utente"])
async def create_attivita(
    id_arnia: int,
    attivita: AttivitaCreate,
    current_user: dict = Depends(get_current_active_user)
):
    """
    Registra una nuova attività per un'arnia

    Args:
        id_arnia: ID dell'arnia
        attivita: Dati dell'attività

    Returns:
        Attività creata
    """
    require_arnia_access(
        current_user, id_arnia, "write", "Non hai permessi di scrittura su questa arnia"
    )

    with db_operation("creazione attività") as cursor:
        return attivita_service.create_attivita(
            cursor, current_user['id_utente'], id_arnia, attivita
        )


@app.patch("/api/user/arnie/{id_arnia}/attivita/{id_log}", response_model=AttivitaResponse, tags=["Utente"])
async def update_user_attivita(
    id_arnia: int,
    id_log: int,
    attivita_update: AttivitaUpdate,
    current_user: Dict = Depends(get_current_active_user)
):
    """
    Aggiorna un'attività di un'arnia (solo se appartiene all'utente)
    """
    require_arnia_access(
        current_user, id_arnia, "write", "Non hai permessi di scrittura su questa arnia"
    )

    with db_operation("aggiornamento attività") as cursor:
        return attivita_service.update_attivita(
            cursor, id_log, id_arnia, current_user['id_utente'], attivita_update
        )


@app.delete("/api/user/arnie/{id_arnia}/attivita/{id_log}", response_model=MessageResponse, tags=["Utente"])
async def delete_user_attivita(
    id_arnia: int,
    id_log: int,
    current_user: Dict = Depends(get_current_active_user)
):
    """
    Elimina un'attività di un'arnia (solo se appartiene all'utente)
    """
    require_arnia_access(
        current_user, id_arnia, "write", "Non hai permessi di scrittura su questa arnia"
    )

    with db_operation("eliminazione attività") as cursor:
        attivita_service.delete_attivita(cursor, id_log, id_arnia, current_user['id_utente'])
        return {"message": "Attività eliminata con successo"}


@app.get("/api/user/arnie/{id_arnia}/letture/temperatura", response_model=List[SerieTemperaturaResponse], tags=["Utente"])
async def get_serie_temperatura(
    id_arnia: int,
    data_inizio: Optional[datetime] = Query(None, description="Data inizio (default: 1 anno fa)"),
    data_fine: Optional[datetime] = Query(None, description="Data fine (default: ora)"),
    limit: int = Query(1000, ge=1, le=10000, description="Numero massimo di letture"),
    current_user: dict = Depends(get_current_active_user)
):
    """
    Serie storica temperatura per un'arnia.
    Restituisce solo timestamp e temperatura, ottimizzato per grafici.
    """
    require_arnia_access(current_user, id_arnia, "read", "Non hai accesso a questa arnia")

    with db_operation("serie temperatura") as cursor:
        return letture_service.get_series(
            cursor, id_arnia, "temperatura", data_inizio, data_fine, limit
        )


@app.get("/api/user/arnie/{id_arnia}/letture/umidita", response_model=List[SerieUmiditaResponse], tags=["Utente"])
async def get_serie_umidita(
    id_arnia: int,
    data_inizio: Optional[datetime] = Query(None, description="Data inizio (default: 1 anno fa)"),
    data_fine: Optional[datetime] = Query(None, description="Data fine (default: ora)"),
    limit: int = Query(1000, ge=1, le=10000, description="Numero massimo di letture"),
    current_user: dict = Depends(get_current_active_user)
):
    """
    Serie storica umidità per un'arnia.
    Restituisce solo timestamp e umidita, ottimizzato per grafici.
    """
    require_arnia_access(current_user, id_arnia, "read", "Non hai accesso a questa arnia")

    with db_operation("serie umidita") as cursor:
        return letture_service.get_series(
            cursor, id_arnia, "umidita", data_inizio, data_fine, limit
        )


@app.get("/api/user/arnie/{id_arnia}/letture/peso", response_model=List[SeriePesoResponse], tags=["Utente"])
async def get_serie_peso(
    id_arnia: int,
    data_inizio: Optional[datetime] = Query(None, description="Data inizio (default: 1 anno fa)"),
    data_fine: Optional[datetime] = Query(None, description="Data fine (default: ora)"),
    limit: int = Query(1000, ge=1, le=10000, description="Numero massimo di letture"),
    current_user: dict = Depends(get_current_active_user)
):
    """
    Serie storica peso per un'arnia.
    Restituisce solo timestamp e peso, ottimizzato per grafici.
    """
    require_arnia_access(current_user, id_arnia, "read", "Non hai accesso a questa arnia")

    with db_operation("serie peso") as cursor:
        return letture_service.get_series(
            cursor, id_arnia, "peso", data_inizio, data_fine, limit
        )



# ============================================
# ENDPOINT ADMIN
# ============================================

@app.get("/api/admin/utenti", response_model=List[UserResponse], tags=["Admin"])
async def get_all_users(current_user: dict = Depends(get_current_admin_user)):
    """
    Ottieni lista di tutti gli utenti (solo admin)

    Returns:
        Lista di tutti gli utenti
    """
    with db_operation("recupero utenti") as cursor:
        return utenti_service.list_utenti(cursor)


@app.post("/api/admin/utenti", response_model=UserResponse, tags=["Admin"])
async def create_user(
    user: UserCreate,
    current_user: dict = Depends(get_current_admin_user)
):
    """
    Crea un nuovo utente (solo admin)

    Args:
        user: Dati del nuovo utente

    Returns:
        Utente creato
    """
    with db_operation("creazione utente") as cursor:
        return utenti_service.create_utente(cursor, user)


@app.put("/api/admin/utenti/{id_utente}", response_model=UserResponse, tags=["Admin"])
async def update_user(
    id_utente: int,
    user_update: UserUpdate,
    current_user: dict = Depends(get_current_admin_user)
):
    """
    Aggiorna un utente (solo admin)

    Args:
        id_utente: ID dell'utente da aggiornare
        user_update: Dati da aggiornare

    Returns:
        Utente aggiornato
    """
    with db_operation("aggiornamento utente") as cursor:
        return utenti_service.update_utente(cursor, id_utente, user_update)


@app.get("/api/admin/nodi", response_model=List[NodoResponse], tags=["Admin"])
async def get_all_nodi(current_user: dict = Depends(get_current_admin_user)):
    """
    Ottieni lista di tutti i nodi (solo admin)

    Returns:
        Lista di tutti i nodi trasmettitori
    """
    with db_operation("recupero nodi") as cursor:
        return nodi_service.list_nodi(cursor)


@app.get("/api/admin/arnie", response_model=List[ArniaConStato], tags=["Admin"])
async def get_all_arnie(current_user: dict = Depends(get_current_admin_user)):
    """
    Ottieni lista di tutte le arnie con stato (solo admin)

    Returns:
        Lista di tutte le arnie
    """
    with db_operation("recupero arnie") as cursor:
        return arnie_service.list_all(cursor)


@app.post("/api/admin/arnie", response_model=ArniaResponse, tags=["Admin"])
async def create_arnia(
    arnia: ArniaCreate,
    current_user: dict = Depends(get_current_admin_user)
):
    """
    Crea una nuova arnia (solo admin)

    Args:
        arnia: Dati della nuova arnia

    Returns:
        Arnia creata
    """
    with db_operation("creazione arnia") as cursor:
        return arnie_service.create_arnia(cursor, arnia)


@app.post("/api/admin/utenti-arnie", response_model=MessageResponse, tags=["Admin"])
async def associate_user_arnia(
    associazione: UtenteArniaCreate,
    current_user: dict = Depends(get_current_admin_user)
):
    """
    Associa un utente a un'arnia (solo admin)

    Args:
        associazione: Dati dell'associazione

    Returns:
        Messaggio di conferma
    """
    with db_operation("associazione utente-arnia") as cursor:
        accessi_service.grant(cursor, associazione)
        return {"message": "Associazione creata con successo"}


@app.get("/api/admin/letture", response_model=List[LetturaResponse], tags=["Admin"])
async def get_all_letture(
    limit: int = Query(1000, ge=1, le=10000),
    current_user: dict = Depends(get_current_admin_user)
):
    """
    Ottieni tutte le letture (solo admin)

    Args:
        limit: Numero massimo di letture da restituire

    Returns:
        Lista di letture
    """
    with db_operation("recupero letture") as cursor:
        return letture_service.list_all(cursor, limit)


@app.get("/api/admin/attivita", response_model=List[AttivitaResponse], tags=["Admin"])
async def get_all_attivita(
    limit: int = Query(100, ge=1, le=1000),
    current_user: dict = Depends(get_current_admin_user)
):
    """
    Ottieni tutte le attività (solo admin)

    Args:
        limit: Numero massimo di attività da restituire

    Returns:
        Lista di attività
    """
    with db_operation("recupero attività") as cursor:
        return attivita_service.list_all(cursor, limit)



# ============================================
# ENDPOINT ADMIN - NODI
# ============================================

@app.post("/api/admin/nodi", response_model=NodoResponse, tags=["Admin - Nodi"])
async def create_nodo(
    nodo: NodoCreate,
    current_user: dict = Depends(get_current_admin_user)
):
    """
    Registra un nuovo nodo trasmettitore (solo admin).
    """
    with db_operation("creazione nodo") as cursor:
        return nodi_service.create_nodo(cursor, nodo)


@app.get("/api/admin/nodi/{id_nodo}", response_model=NodoResponse, tags=["Admin - Nodi"])
async def get_nodo(
    id_nodo: str,
    current_user: dict = Depends(get_current_admin_user)
):
    """
    Dettagli di un singolo nodo (solo admin).
    """
    with db_operation("recupero nodo") as cursor:
        return nodi_service.get_nodo(cursor, id_nodo)


@app.put("/api/admin/nodi/{id_nodo}", response_model=NodoResponse, tags=["Admin - Nodi"])
async def update_nodo(
    id_nodo: str,
    nodo: NodoCreate,
    current_user: dict = Depends(get_current_admin_user)
):
    """
    Aggiorna un nodo esistente (solo admin).
    """
    with db_operation("aggiornamento nodo") as cursor:
        return nodi_service.update_nodo(cursor, id_nodo, nodo)


@app.delete("/api/admin/nodi/{id_nodo}", response_model=MessageResponse, tags=["Admin - Nodi"])
async def delete_nodo(
    id_nodo: str,
    current_user: dict = Depends(get_current_admin_user)
):
    """
    Disattiva un nodo (soft delete, solo admin).
    Le arnie e le letture associate vengono mantenute.
    """
    with db_operation("disattivazione nodo") as cursor:
        nodi_service.deactivate_nodo(cursor, id_nodo)
        return {"message": f"Nodo '{id_nodo}' disattivato con successo"}


# ============================================
# ENDPOINT ADMIN - ARNIE (crud completo)
# ============================================

@app.get("/api/admin/arnie/{id_arnia}", response_model=ArniaConStato, tags=["Admin - Arnie"])
async def get_arnia_admin(
    id_arnia: int,
    current_user: dict = Depends(get_current_admin_user)
):
    """
    Dettagli di una singola arnia con ultimo stato (solo admin).
    """
    with db_operation("recupero arnia") as cursor:
        return arnie_service.get_arnia(cursor, id_arnia)


@app.put("/api/admin/arnie/{id_arnia}", response_model=ArniaResponse, tags=["Admin - Arnie"])
async def update_arnia_admin(
    id_arnia: int,
    arnia: ArniaUpdate,
    current_user: dict = Depends(get_current_admin_user)
):
    """
    Aggiorna una arnia (solo admin).
    """
    with db_operation("aggiornamento arnia") as cursor:
        return arnie_service.update_arnia(cursor, id_arnia, arnia, allow_attiva=True)


@app.delete("/api/admin/arnie/{id_arnia}", response_model=MessageResponse, tags=["Admin - Arnie"])
async def delete_arnia(
    id_arnia: int,
    current_user: dict = Depends(get_current_admin_user)
):
    """
    Disattiva un'arnia (soft delete, solo admin).
    Le letture storiche vengono mantenute.
    """
    with db_operation("disattivazione arnia") as cursor:
        arnie_service.deactivate_arnia(cursor, id_arnia)
        return {"message": f"Arnia {id_arnia} disattivata con successo"}


@app.delete("/api/admin/utenti-arnie", response_model=MessageResponse, tags=["Admin - Utenti"])
async def remove_user_arnia(
    id_utente: int,
    id_arnia: int,
    current_user: dict = Depends(get_current_admin_user)
):
    """
    Rimuove l'associazione tra un utente e un'arnia (solo admin).
    """
    with db_operation("rimozione associazione") as cursor:
        accessi_service.revoke(cursor, id_utente, id_arnia)
        return {"message": f"Associazione utente {id_utente} - arnia {id_arnia} rimossa"}


@app.delete("/api/admin/utenti/{id_utente}", response_model=MessageResponse, tags=["Admin - Utenti"])
async def delete_user(
    id_utente: int,
    current_user: dict = Depends(get_current_admin_user)
):
    """
    Disattiva un utente (soft delete, solo admin).
    Non è possibile disattivare se stessi.
    """
    with db_operation("disattivazione utente") as cursor:
        utenti_service.deactivate_utente(
            cursor, id_utente, acting_user_id=current_user["id_utente"]
        )
        return {"message": f"Utente {id_utente} disattivato con successo"}


@app.put("/api/admin/utenti/{id_utente}/password", response_model=MessageResponse, tags=["Admin - Utenti"])
async def reset_user_password(
    id_utente: int,
    body: PasswordChange,
    current_user: dict = Depends(get_current_admin_user)
):
    """
    Reset password di un utente (solo admin).
    """
    with db_operation("reset password") as cursor:
        utenti_service.reset_password(cursor, id_utente, body.new_password)
    return {"message": "Password aggiornata con successo"}


# ============================================
# ENDPOINT USER - ARNIE (update permesso write)
# ============================================

@app.get("/api/user/arnie/{id_arnia}", response_model=ArniaConStato, tags=["Utente"])
async def get_arnia_user(
    id_arnia: int,
    current_user: dict = Depends(get_current_active_user)
):
    """
    Dettagli di una singola arnia con ultimo stato.
    """
    require_arnia_access(current_user, id_arnia, "read", "Non hai accesso a questa arnia")

    with db_operation("recupero arnia") as cursor:
        return arnie_service.get_arnia(cursor, id_arnia)


@app.put("/api/user/arnie/{id_arnia}", response_model=ArniaResponse, tags=["Utente"])
async def update_arnia_user(
    id_arnia: int,
    arnia: ArniaUpdate,
    current_user: dict = Depends(get_current_active_user)
):
    """
    Aggiorna un'arnia (richiede permesso write o admin sull'arnia).
    Campi modificabili: nome, descrizione, posizione, coordinate, metadati.
    Non è possibile modificare attiva (usa admin per quello).
    """
    require_arnia_access(
        current_user, id_arnia, "write", "Permessi insufficienti su questa arnia"
    )

    with db_operation("aggiornamento arnia") as cursor:
        return arnie_service.update_arnia(cursor, id_arnia, arnia, allow_attiva=False)


@app.put("/api/user/password", response_model=MessageResponse, tags=["Utente"])
async def change_own_password(
    body: PasswordChange,
    current_user: dict = Depends(get_current_active_user)
):
    """
    Cambia la propria password.
    """
    with db_operation("cambio password") as cursor:
        utenti_service.change_own_password(
            cursor, current_user["id_utente"], body.current_password, body.new_password
        )
    return {"message": "Password aggiornata con successo"}


@app.post("/api/admin/letture", response_model=LetturaResponse, tags=["Admin - Nodi"])
async def create_lettura_manuale(
    lettura: LetturaCreate,
    current_user: dict = Depends(get_current_admin_user)
):
    """
    Inserisce una lettura manualmente (solo admin, utile per test e backfill).
    """
    with db_operation("inserimento lettura") as cursor:
        return letture_service.record_reading(cursor, lettura)

# ============================================
# ENDPOINT INFO E HEALTH
# ============================================

@app.get("/", tags=["Info"])
async def root():
    """Endpoint root con informazioni API"""
    return {
        "name": settings.API_TITLE,
        "version": settings.API_VERSION,
        "description": settings.API_DESCRIPTION,
        "docs_url": "/docs",
        "redoc_url": "/redoc"
    }


@app.get("/health", tags=["Info"])
async def health_check():
    """Health check endpoint"""
    try:
        # Verifica connessione database
        with get_db_cursor() as cursor:
            ping(cursor)

        return {
            "status": "healthy",
            "database": "connected",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "database": "disconnected",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
