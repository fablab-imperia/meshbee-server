"""
Beehive IoT API - Applicazione principale

Thin HTTP layer: each handler validates its input, opens a session, calls one
service in `meshbee_core`, and returns the result. There is no SQL here — see
README.md for where new code belongs.

Handlers are plain `def`, not `async def`: the database calls are synchronous,
so FastAPI must run them in its threadpool rather than on the event loop.
"""

import logging
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.auth import (
    authenticate_user,
    check_user_apiario_access,
    check_user_arnia_access,
    create_access_token,
    create_refresh_token,
    get_current_active_user,
    get_current_admin_user,
)
from api.config import settings
from api.paging import PAGED_RESPONSES, TOTAL_HEADER, page_items, paging_query
from meshbee_core.db import close_db_pool, get_session, init_db_pool, ping
from meshbee_core.errors import Conflict, InvalidData, NotFound
from meshbee_core.models import (
    ApiarioAdminCreate,
    ApiarioConAccesso,
    ApiarioCreate,
    ApiarioResponse,
    ApiarioUpdate,
    ArniaApiarioUpdate,
    ArniaConStato,
    ArniaCreate,
    ArniaResponse,
    ArniaUpdate,
    AttivitaCreate,
    AttivitaResponse,
    AttivitaUpdate,
    CondivisioneCreate,
    CondivisioneResponse,
    CondivisioneUpdate,
    LetturaCreate,
    LetturaResponse,
    LetturaUpdate,
    LettureDelete,
    MessageResponse,
    NodoCreate,
    NodoProprietarioUpdate,
    NodoResponse,
    PasswordChange,
    SerieBatteriaResponse,
    SeriePesoResponse,
    SerieTemperaturaResponse,
    SerieUmiditaResponse,
    Token,
    UserCreate,
    UserLogin,
    UserResponse,
    UserUpdate,
)
from meshbee_core.paging import Paging
from meshbee_core.services import (
    accessi as accessi_service,
)
from meshbee_core.services import (
    apiari as apiari_service,
)
from meshbee_core.services import (
    arnie as arnie_service,
)
from meshbee_core.services import (
    attivita as attivita_service,
)
from meshbee_core.services import (
    letture as letture_service,
)
from meshbee_core.services import (
    nodi as nodi_service,
)
from meshbee_core.services import (
    utenti as utenti_service,
)

# Configurazione logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
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
    lifespan=lifespan,
)

# Configurazione CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # A cross-origin client can read a paged list's total only if it is exposed.
    expose_headers=[TOTAL_HEADER],
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
    Open a session and turn a failed service call into the right status code.

    `descrizione` only ever reaches the log line for an unexpected failure —
    the response for those stays deliberately vague, since the exception text
    may name tables or columns.
    """
    try:
        with get_session() as session:
            yield session
    except HTTPException:
        raise
    except tuple(ERROR_STATUS) as e:
        raise HTTPException(status_code=ERROR_STATUS[type(e)], detail=str(e)) from e
    except Exception as e:
        logger.error(f"Errore {descrizione}: {e}")
        raise HTTPException(status_code=500, detail="Errore interno del server") from e


def require_arnia_access(current_user: dict, id_arnia: int, action: str, detail: str):
    """
    Guard an arnia-scoped endpoint, answering 403 when the user may not
    perform `action` (see `meshbee_core/services/auth.py`).
    """
    if not check_user_arnia_access(current_user["id_utente"], id_arnia, action):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def require_apiario_access(current_user: dict, id_apiario: int, action: str):
    """Guard an apiary-scoped endpoint, answering 403 when the user may not act."""
    if not check_user_apiario_access(current_user["id_utente"], id_apiario, action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permessi insufficienti su questo apiario",
        )


# Shared by every hive list that can be narrowed to one apiary.
ID_APIARIO_FILTER = Query(None, description="Solo le arnie di questo apiario")

# `limit` and `offset` on the list routes (api/paging.py). The readings and
# activities keep the default and maximum `limit` they had before paging.
PAGING = Depends(paging_query())
LETTURE_PAGING = Depends(paging_query(1000, 10000, "letture"))
ATTIVITA_PAGING = Depends(paging_query(100, 1000, "attività"))


def message_for_deleted_apiario(id_apiario: int) -> dict:
    return {"message": f"Apiario {id_apiario} eliminato con successo"}


# ============================================
# ENDPOINT AUTENTICAZIONE
# ============================================


@app.post("/api/auth/login", response_model=Token, tags=["Autenticazione"])
def login(user_login: UserLogin):
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
    access_token = create_access_token(data={"sub": user["email"]})
    refresh_token = create_refresh_token(data={"sub": user["email"]})

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@app.get("/api/auth/me", response_model=UserResponse, tags=["Autenticazione"])
def get_me(current_user: dict = Depends(get_current_active_user)):
    """
    Ottieni informazioni sull'utente corrente

    Returns:
        Dati dell'utente autenticato
    """
    return current_user


# ============================================
# ENDPOINT UTENTE (User APIs)
# ============================================


@app.get(
    "/api/user/arnie",
    response_model=list[ArniaConStato],
    tags=["Utente"],
    responses=PAGED_RESPONSES,
)
def get_user_arnie(
    response: Response,
    id_apiario: int | None = ID_APIARIO_FILTER,
    paging: Paging = PAGING,
    current_user: dict = Depends(get_current_active_user),
):
    """
    Ottieni lista delle arnie associate all'utente con lo stato attuale

    Returns:
        Lista di arnie con ultime letture
    """
    with db_operation("recupero arnie utente") as session:
        return page_items(
            response,
            arnie_service.list_for_utente(session, current_user, id_apiario, paging),
        )


@app.get(
    "/api/user/apiari",
    response_model=list[ApiarioConAccesso],
    tags=["Utente"],
    responses=PAGED_RESPONSES,
)
def get_user_apiari(
    response: Response,
    paging: Paging = PAGING,
    current_user: dict = Depends(get_current_active_user),
):
    """
    The apiaries the caller owns (the default one first), then those shared
    with them; `accesso` says which. Their hives: `GET /api/user/arnie?id_apiario=...`.
    """
    with db_operation("recupero apiari utente") as session:
        return page_items(
            response,
            apiari_service.list_for_utente(session, current_user["id_utente"], paging),
        )


@app.post("/api/user/apiari", response_model=ApiarioResponse, tags=["Utente"])
def create_user_apiario(
    apiario: ApiarioCreate, current_user: dict = Depends(get_current_active_user)
):
    """
    Create an apiary owned by the caller.
    """
    with db_operation("creazione apiario") as session:
        return apiari_service.create_apiario(
            session, current_user["id_utente"], apiario
        )


@app.get(
    "/api/user/apiari/{id_apiario}",
    response_model=ApiarioConAccesso,
    tags=["Utente"],
)
def get_apiario_user(
    id_apiario: int, current_user: dict = Depends(get_current_active_user)
):
    """
    One apiary the caller owns or has been shared.
    """
    require_apiario_access(current_user, id_apiario, "apiario.read")

    with db_operation("recupero apiario") as session:
        return apiari_service.get_for_utente(
            session, id_apiario, current_user["id_utente"]
        )


@app.put(
    "/api/user/apiari/{id_apiario}", response_model=ApiarioResponse, tags=["Utente"]
)
def update_apiario_user(
    id_apiario: int,
    apiario: ApiarioUpdate,
    current_user: dict = Depends(get_current_active_user),
):
    """
    Edit an apiary, the default one included (owner or manager).
    """
    require_apiario_access(current_user, id_apiario, "apiario.update")

    with db_operation("aggiornamento apiario") as session:
        return apiari_service.update_apiario(session, id_apiario, apiario)


@app.delete(
    "/api/user/apiari/{id_apiario}", response_model=MessageResponse, tags=["Utente"]
)
def delete_apiario_user(
    id_apiario: int, current_user: dict = Depends(get_current_active_user)
):
    """
    Delete an apiary (owner only).
    Refused with 409 for the default one, and while hives are still in it.
    """
    require_apiario_access(current_user, id_apiario, "apiario.delete")

    with db_operation("eliminazione apiario") as session:
        apiari_service.delete_apiario(session, id_apiario)
        return message_for_deleted_apiario(id_apiario)


@app.get(
    "/api/user/apiari/{id_apiario}/condivisioni",
    response_model=list[CondivisioneResponse],
    tags=["Utente"],
    responses=PAGED_RESPONSES,
)
def get_condivisioni(
    response: Response,
    id_apiario: int,
    paging: Paging = PAGING,
    current_user: dict = Depends(get_current_active_user),
):
    """
    Who the apiary is shared with, and as what (owner only).
    """
    require_apiario_access(current_user, id_apiario, "apiario.share")

    with db_operation("recupero condivisioni") as session:
        return page_items(
            response, accessi_service.list_condivisioni(session, id_apiario, paging)
        )


@app.post(
    "/api/user/apiari/{id_apiario}/condivisioni",
    response_model=CondivisioneResponse,
    tags=["Utente"],
)
def share_apiario(
    id_apiario: int,
    condivisione: CondivisioneCreate,
    current_user: dict = Depends(get_current_active_user),
):
    """
    Share the apiary with a user, by email, as viewer, collaborator or manager
    (owner only). Sharing again with the same user changes their role.
    """
    require_apiario_access(current_user, id_apiario, "apiario.share")

    with db_operation("condivisione apiario") as session:
        return accessi_service.share(session, id_apiario, condivisione)


@app.put(
    "/api/user/apiari/{id_apiario}/condivisioni/{id_utente}",
    response_model=CondivisioneResponse,
    tags=["Utente"],
)
def update_condivisione(
    id_apiario: int,
    id_utente: int,
    body: CondivisioneUpdate,
    current_user: dict = Depends(get_current_active_user),
):
    """
    Change the role of an existing share (owner only).
    """
    require_apiario_access(current_user, id_apiario, "apiario.share")

    with db_operation("aggiornamento condivisione") as session:
        return accessi_service.change_ruolo(session, id_apiario, id_utente, body.ruolo)


@app.delete(
    "/api/user/apiari/{id_apiario}/condivisioni/{id_utente}",
    response_model=MessageResponse,
    tags=["Utente"],
)
def revoke_condivisione(
    id_apiario: int,
    id_utente: int,
    current_user: dict = Depends(get_current_active_user),
):
    """
    Stop sharing the apiary with a user (owner only).
    """
    require_apiario_access(current_user, id_apiario, "apiario.share")

    with db_operation("revoca condivisione") as session:
        accessi_service.revoke(session, id_apiario, id_utente)
        return {"message": "Condivisione rimossa"}


@app.put(
    "/api/user/arnie/{id_arnia}/apiario",
    response_model=ArniaResponse,
    tags=["Utente"],
)
def move_arnia_user(
    id_arnia: int,
    body: ArniaApiarioUpdate,
    current_user: dict = Depends(get_current_active_user),
):
    """
    Move a hive into another apiary of its owner (owner only).
    Who can see it follows the apiary it lands in.
    """
    require_arnia_access(
        current_user,
        id_arnia,
        "arnia.move",
        "Solo il proprietario può spostare l'arnia",
    )

    with db_operation("spostamento arnia") as session:
        return arnie_service.move_arnia(session, id_arnia, body.id_apiario)


@app.get(
    "/api/user/arnie/{id_arnia}/letture",
    response_model=list[LetturaResponse],
    tags=["Utente"],
    responses=PAGED_RESPONSES,
)
def get_user_letture(
    response: Response,
    id_arnia: int,
    data_inizio: datetime | None = Query(
        None, description="Data inizio (default: 1 anno fa)"
    ),
    data_fine: datetime | None = Query(None, description="Data fine (default: ora)"),
    paging: Paging = LETTURE_PAGING,
    current_user: dict = Depends(get_current_active_user),
):
    """
    Ottieni letture di un'arnia

    Args:
        id_arnia: ID dell'arnia
        data_inizio: Data inizio periodo (opzionale)
        data_fine: Data fine periodo (opzionale)
        limit, offset: Paginazione (opzionale)

    Returns:
        Lista di letture ordinate per timestamp (più recente prima)
    """
    require_arnia_access(
        current_user, id_arnia, "arnia.read", "Non hai accesso a questa arnia"
    )

    with db_operation("recupero letture") as session:
        return page_items(
            response,
            letture_service.list_for_arnia(
                session, id_arnia, data_inizio, data_fine, paging
            ),
        )


@app.get(
    "/api/user/arnie/{id_arnia}/attivita",
    response_model=list[AttivitaResponse],
    tags=["Utente"],
    responses=PAGED_RESPONSES,
)
def get_user_attivita(
    response: Response,
    id_arnia: int,
    data_inizio: datetime | None = Query(
        None, description="Data inizio (default: 1 anno fa)"
    ),
    data_fine: datetime | None = Query(None, description="Data fine (default: ora)"),
    tipo_attivita: str | None = Query(None, description="Filtra per tipo attività"),
    paging: Paging = ATTIVITA_PAGING,
    current_user: dict = Depends(get_current_active_user),
):
    """
    Ottieni log attività di un'arnia

    Args:
        id_arnia: ID dell'arnia
        data_inizio: Data inizio periodo (opzionale)
        data_fine: Data fine periodo (opzionale)
        tipo_attivita: Tipo di attività (opzionale)
        limit, offset: Paginazione (opzionale)

    Returns:
        Lista di attività ordinate per timestamp (più recente prima)
    """
    require_arnia_access(
        current_user, id_arnia, "arnia.read", "Non hai accesso a questa arnia"
    )

    with db_operation("recupero attività") as session:
        return page_items(
            response,
            attivita_service.list_for_arnia(
                session, id_arnia, data_inizio, data_fine, paging, tipo_attivita
            ),
        )


@app.post(
    "/api/user/arnie/{id_arnia}/attivita",
    response_model=AttivitaResponse,
    tags=["Utente"],
)
def create_attivita(
    id_arnia: int,
    attivita: AttivitaCreate,
    current_user: dict = Depends(get_current_active_user),
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
        current_user,
        id_arnia,
        "attivita.write",
        "Non hai permessi di scrittura su questa arnia",
    )

    with db_operation("creazione attività") as session:
        return attivita_service.create_attivita(
            session, current_user["id_utente"], id_arnia, attivita
        )


@app.patch(
    "/api/user/arnie/{id_arnia}/attivita/{id_log}",
    response_model=AttivitaResponse,
    tags=["Utente"],
)
def update_user_attivita(
    id_arnia: int,
    id_log: int,
    attivita_update: AttivitaUpdate,
    current_user: dict = Depends(get_current_active_user),
):
    """
    Aggiorna un'attività di un'arnia (solo se appartiene all'utente)
    """
    require_arnia_access(
        current_user,
        id_arnia,
        "attivita.write",
        "Non hai permessi di scrittura su questa arnia",
    )

    with db_operation("aggiornamento attività") as session:
        return attivita_service.update_attivita(
            session, id_log, id_arnia, current_user["id_utente"], attivita_update
        )


@app.delete(
    "/api/user/arnie/{id_arnia}/attivita/{id_log}",
    response_model=MessageResponse,
    tags=["Utente"],
)
def delete_user_attivita(
    id_arnia: int, id_log: int, current_user: dict = Depends(get_current_active_user)
):
    """
    Elimina un'attività di un'arnia (solo se appartiene all'utente)
    """
    require_arnia_access(
        current_user,
        id_arnia,
        "attivita.write",
        "Non hai permessi di scrittura su questa arnia",
    )

    with db_operation("eliminazione attività") as session:
        attivita_service.delete_attivita(
            session, id_log, id_arnia, current_user["id_utente"]
        )
        return {"message": "Attività eliminata con successo"}


@app.get(
    "/api/user/arnie/{id_arnia}/letture/temperatura",
    response_model=list[SerieTemperaturaResponse],
    tags=["Utente"],
)
def get_serie_temperatura(
    id_arnia: int,
    data_inizio: datetime | None = Query(
        None, description="Data inizio (default: 1 anno fa)"
    ),
    data_fine: datetime | None = Query(None, description="Data fine (default: ora)"),
    limit: int = Query(1000, ge=1, le=10000, description="Numero massimo di letture"),
    current_user: dict = Depends(get_current_active_user),
):
    """
    Serie storica temperatura per un'arnia.
    Restituisce solo timestamp e temperatura, ottimizzato per grafici.
    """
    require_arnia_access(
        current_user, id_arnia, "arnia.read", "Non hai accesso a questa arnia"
    )

    with db_operation("serie temperatura") as session:
        return letture_service.get_series(
            session, id_arnia, "temperatura", data_inizio, data_fine, limit
        )


@app.get(
    "/api/user/arnie/{id_arnia}/letture/umidita",
    response_model=list[SerieUmiditaResponse],
    tags=["Utente"],
)
def get_serie_umidita(
    id_arnia: int,
    data_inizio: datetime | None = Query(
        None, description="Data inizio (default: 1 anno fa)"
    ),
    data_fine: datetime | None = Query(None, description="Data fine (default: ora)"),
    limit: int = Query(1000, ge=1, le=10000, description="Numero massimo di letture"),
    current_user: dict = Depends(get_current_active_user),
):
    """
    Serie storica umidità per un'arnia.
    Restituisce solo timestamp e umidita, ottimizzato per grafici.
    """
    require_arnia_access(
        current_user, id_arnia, "arnia.read", "Non hai accesso a questa arnia"
    )

    with db_operation("serie umidita") as session:
        return letture_service.get_series(
            session, id_arnia, "umidita", data_inizio, data_fine, limit
        )


@app.get(
    "/api/user/arnie/{id_arnia}/letture/peso",
    response_model=list[SeriePesoResponse],
    tags=["Utente"],
)
def get_serie_peso(
    id_arnia: int,
    data_inizio: datetime | None = Query(
        None, description="Data inizio (default: 1 anno fa)"
    ),
    data_fine: datetime | None = Query(None, description="Data fine (default: ora)"),
    limit: int = Query(1000, ge=1, le=10000, description="Numero massimo di letture"),
    current_user: dict = Depends(get_current_active_user),
):
    """
    Serie storica peso per un'arnia.
    Restituisce solo timestamp e peso, ottimizzato per grafici.
    """
    require_arnia_access(
        current_user, id_arnia, "arnia.read", "Non hai accesso a questa arnia"
    )

    with db_operation("serie peso") as session:
        return letture_service.get_series(
            session, id_arnia, "peso", data_inizio, data_fine, limit
        )


@app.get(
    "/api/user/arnie/{id_arnia}/letture/batteria",
    response_model=list[SerieBatteriaResponse],
    tags=["Utente"],
)
def get_serie_batteria(
    id_arnia: int,
    data_inizio: datetime | None = Query(
        None, description="Data inizio (default: 1 anno fa)"
    ),
    data_fine: datetime | None = Query(None, description="Data fine (default: ora)"),
    limit: int = Query(1000, ge=1, le=10000, description="Numero massimo di letture"),
    current_user: dict = Depends(get_current_active_user),
):
    """
    Battery voltage time series for one hive's node.
    Returns only timestamp and batteria, shaped for charts.
    """
    require_arnia_access(
        current_user, id_arnia, "arnia.read", "Non hai accesso a questa arnia"
    )

    with db_operation("serie batteria") as session:
        return letture_service.get_series(
            session, id_arnia, "batteria", data_inizio, data_fine, limit
        )


# ============================================
# ENDPOINT ADMIN
# ============================================


@app.get(
    "/api/admin/utenti",
    response_model=list[UserResponse],
    tags=["Admin"],
    responses=PAGED_RESPONSES,
)
def get_all_users(
    response: Response,
    paging: Paging = PAGING,
    current_user: dict = Depends(get_current_admin_user),
):
    """
    Ottieni lista di tutti gli utenti (solo admin)

    Returns:
        Lista di tutti gli utenti
    """
    with db_operation("recupero utenti") as session:
        return page_items(response, utenti_service.list_utenti(session, paging))


@app.post("/api/admin/utenti", response_model=UserResponse, tags=["Admin"])
def create_user(user: UserCreate, current_user: dict = Depends(get_current_admin_user)):
    """
    Crea un nuovo utente (solo admin)

    Args:
        user: Dati del nuovo utente

    Returns:
        Utente creato
    """
    with db_operation("creazione utente") as session:
        return utenti_service.create_utente(session, user)


@app.put("/api/admin/utenti/{id_utente}", response_model=UserResponse, tags=["Admin"])
def update_user(
    id_utente: int,
    user_update: UserUpdate,
    current_user: dict = Depends(get_current_admin_user),
):
    """
    Aggiorna un utente (solo admin)

    Args:
        id_utente: ID dell'utente da aggiornare
        user_update: Dati da aggiornare

    Returns:
        Utente aggiornato
    """
    with db_operation("aggiornamento utente") as session:
        return utenti_service.update_utente(session, id_utente, user_update)


@app.get(
    "/api/admin/nodi",
    response_model=list[NodoResponse],
    tags=["Admin"],
    responses=PAGED_RESPONSES,
)
def get_all_nodi(
    response: Response,
    paging: Paging = PAGING,
    current_user: dict = Depends(get_current_admin_user),
):
    """
    Ottieni lista di tutti i nodi (solo admin)

    Returns:
        Lista di tutti i nodi trasmettitori
    """
    with db_operation("recupero nodi") as session:
        return page_items(response, nodi_service.list_nodi(session, paging))


@app.get(
    "/api/admin/arnie",
    response_model=list[ArniaConStato],
    tags=["Admin"],
    responses=PAGED_RESPONSES,
)
def get_all_arnie(
    response: Response,
    id_apiario: int | None = ID_APIARIO_FILTER,
    paging: Paging = PAGING,
    current_user: dict = Depends(get_current_admin_user),
):
    """
    Ottieni lista di tutte le arnie con stato (solo admin)

    Returns:
        Lista di tutte le arnie
    """
    with db_operation("recupero arnie") as session:
        return page_items(response, arnie_service.list_all(session, id_apiario, paging))


@app.post("/api/admin/arnie", response_model=ArniaResponse, tags=["Admin"])
def create_arnia(
    arnia: ArniaCreate, current_user: dict = Depends(get_current_admin_user)
):
    """
    Crea una nuova arnia (solo admin)

    Args:
        arnia: Dati della nuova arnia

    Returns:
        Arnia creata
    """
    with db_operation("creazione arnia") as session:
        return arnie_service.create_arnia(session, arnia)


@app.get(
    "/api/admin/letture",
    response_model=list[LetturaResponse],
    tags=["Admin"],
    responses=PAGED_RESPONSES,
)
def get_all_letture(
    response: Response,
    paging: Paging = LETTURE_PAGING,
    current_user: dict = Depends(get_current_admin_user),
):
    """
    Ottieni tutte le letture (solo admin)

    Args:
        limit, offset: Paginazione (opzionale)

    Returns:
        Lista di letture
    """
    with db_operation("recupero letture") as session:
        return page_items(response, letture_service.list_all(session, paging))


@app.get(
    "/api/admin/attivita",
    response_model=list[AttivitaResponse],
    tags=["Admin"],
    responses=PAGED_RESPONSES,
)
def get_all_attivita(
    response: Response,
    paging: Paging = ATTIVITA_PAGING,
    current_user: dict = Depends(get_current_admin_user),
):
    """
    Ottieni tutte le attività (solo admin)

    Args:
        limit, offset: Paginazione (opzionale)

    Returns:
        Lista di attività
    """
    with db_operation("recupero attività") as session:
        return page_items(response, attivita_service.list_all(session, paging))


# ============================================
# ENDPOINT ADMIN - NODI
# ============================================


@app.post("/api/admin/nodi", response_model=NodoResponse, tags=["Admin - Nodi"])
def create_nodo(nodo: NodoCreate, current_user: dict = Depends(get_current_admin_user)):
    """
    Registra un nuovo nodo trasmettitore (solo admin).
    """
    with db_operation("creazione nodo") as session:
        return nodi_service.create_nodo(session, nodo)


@app.get(
    "/api/admin/nodi/{id_nodo}", response_model=NodoResponse, tags=["Admin - Nodi"]
)
def get_nodo(id_nodo: str, current_user: dict = Depends(get_current_admin_user)):
    """
    Dettagli di un singolo nodo (solo admin).
    """
    with db_operation("recupero nodo") as session:
        return nodi_service.get_nodo(session, id_nodo)


@app.put(
    "/api/admin/nodi/{id_nodo}", response_model=NodoResponse, tags=["Admin - Nodi"]
)
def update_nodo(
    id_nodo: str, nodo: NodoCreate, current_user: dict = Depends(get_current_admin_user)
):
    """
    Aggiorna un nodo esistente (solo admin).
    """
    with db_operation("aggiornamento nodo") as session:
        return nodi_service.update_nodo(session, id_nodo, nodo)


@app.delete(
    "/api/admin/nodi/{id_nodo}", response_model=MessageResponse, tags=["Admin - Nodi"]
)
def delete_nodo(id_nodo: str, current_user: dict = Depends(get_current_admin_user)):
    """
    Disattiva un nodo (soft delete, solo admin).
    Le arnie e le letture associate vengono mantenute.
    """
    with db_operation("disattivazione nodo") as session:
        nodi_service.deactivate_nodo(session, id_nodo)
        return {"message": f"Nodo '{id_nodo}' disattivato con successo"}


@app.put(
    "/api/admin/nodi/{id_nodo}/proprietario",
    response_model=NodoResponse,
    tags=["Admin - Nodi"],
)
def assign_nodo(
    id_nodo: str,
    body: NodoProprietarioUpdate,
    current_user: dict = Depends(get_current_admin_user),
):
    """
    Assign a node to a user, transfer it, or unassign it with null (admin only).
    Its hives move to the new owner's default apiary.
    """
    with db_operation("assegnazione nodo") as session:
        return nodi_service.assign_proprietario(session, id_nodo, body.id_utente)


# ============================================
# ENDPOINT ADMIN - ARNIE (crud completo)
# ============================================


@app.get(
    "/api/admin/arnie/{id_arnia}", response_model=ArniaConStato, tags=["Admin - Arnie"]
)
def get_arnia_admin(
    id_arnia: int, current_user: dict = Depends(get_current_admin_user)
):
    """
    Dettagli di una singola arnia con ultimo stato (solo admin).
    """
    with db_operation("recupero arnia") as session:
        return arnie_service.get_arnia(session, id_arnia)


@app.put(
    "/api/admin/arnie/{id_arnia}", response_model=ArniaResponse, tags=["Admin - Arnie"]
)
def update_arnia_admin(
    id_arnia: int,
    arnia: ArniaUpdate,
    current_user: dict = Depends(get_current_admin_user),
):
    """
    Aggiorna una arnia (solo admin).
    """
    with db_operation("aggiornamento arnia") as session:
        return arnie_service.update_arnia(session, id_arnia, arnia, allow_attiva=True)


@app.delete(
    "/api/admin/arnie/{id_arnia}",
    response_model=MessageResponse,
    tags=["Admin - Arnie"],
)
def delete_arnia(id_arnia: int, current_user: dict = Depends(get_current_admin_user)):
    """
    Disattiva un'arnia (soft delete, solo admin).
    Le letture storiche vengono mantenute.
    """
    with db_operation("disattivazione arnia") as session:
        arnie_service.deactivate_arnia(session, id_arnia)
        return {"message": f"Arnia {id_arnia} disattivata con successo"}


# ============================================
# ENDPOINT ADMIN - APIARI
# ============================================


@app.get(
    "/api/admin/apiari",
    response_model=list[ApiarioResponse],
    tags=["Admin - Apiari"],
    responses=PAGED_RESPONSES,
)
def get_all_apiari(
    response: Response,
    id_utente: int | None = Query(None, description="Solo gli apiari di questo utente"),
    paging: Paging = PAGING,
    current_user: dict = Depends(get_current_admin_user),
):
    """
    Every user's apiaries, or one user's (admin only).
    """
    with db_operation("recupero apiari") as session:
        return page_items(response, apiari_service.list_all(session, id_utente, paging))


@app.post("/api/admin/apiari", response_model=ApiarioResponse, tags=["Admin - Apiari"])
def create_apiario(
    apiario: ApiarioAdminCreate, current_user: dict = Depends(get_current_admin_user)
):
    """
    Create an apiary on behalf of a user (admin only).
    """
    with db_operation("creazione apiario") as session:
        return apiari_service.create_apiario(
            session, apiario.id_utente_proprietario, apiario
        )


@app.get(
    "/api/admin/apiari/{id_apiario}",
    response_model=ApiarioResponse,
    tags=["Admin - Apiari"],
)
def get_apiario_admin(
    id_apiario: int, current_user: dict = Depends(get_current_admin_user)
):
    """
    Any user's apiary (admin only).
    """
    with db_operation("recupero apiario") as session:
        return apiari_service.get_apiario(session, id_apiario)


@app.put(
    "/api/admin/apiari/{id_apiario}",
    response_model=ApiarioResponse,
    tags=["Admin - Apiari"],
)
def update_apiario(
    id_apiario: int,
    apiario: ApiarioUpdate,
    current_user: dict = Depends(get_current_admin_user),
):
    """
    Edit any user's apiary (admin only).
    """
    with db_operation("aggiornamento apiario") as session:
        return apiari_service.update_apiario(session, id_apiario, apiario)


@app.delete(
    "/api/admin/apiari/{id_apiario}",
    response_model=MessageResponse,
    tags=["Admin - Apiari"],
)
def delete_apiario(
    id_apiario: int, current_user: dict = Depends(get_current_admin_user)
):
    """
    Delete any user's apiary (admin only), with the owner's rules: never the
    default one, and not while hives are still in it (409).
    """
    with db_operation("eliminazione apiario") as session:
        apiari_service.delete_apiario(session, id_apiario)
        return message_for_deleted_apiario(id_apiario)


@app.delete(
    "/api/admin/utenti/{id_utente}",
    response_model=MessageResponse,
    tags=["Admin - Utenti"],
)
def delete_user(id_utente: int, current_user: dict = Depends(get_current_admin_user)):
    """
    Disattiva un utente (soft delete, solo admin).
    Non è possibile disattivare se stessi.
    """
    with db_operation("disattivazione utente") as session:
        utenti_service.deactivate_utente(
            session, id_utente, acting_user_id=current_user["id_utente"]
        )
        return {"message": f"Utente {id_utente} disattivato con successo"}


@app.put(
    "/api/admin/utenti/{id_utente}/password",
    response_model=MessageResponse,
    tags=["Admin - Utenti"],
)
def reset_user_password(
    id_utente: int,
    body: PasswordChange,
    current_user: dict = Depends(get_current_admin_user),
):
    """
    Reset password di un utente (solo admin).
    """
    with db_operation("reset password") as session:
        utenti_service.reset_password(session, id_utente, body.new_password)
    return {"message": "Password aggiornata con successo"}


# ============================================
# ENDPOINT USER - ARNIE (update permesso write)
# ============================================


@app.get("/api/user/arnie/{id_arnia}", response_model=ArniaConStato, tags=["Utente"])
def get_arnia_user(
    id_arnia: int, current_user: dict = Depends(get_current_active_user)
):
    """
    Dettagli di una singola arnia con ultimo stato.
    """
    require_arnia_access(
        current_user, id_arnia, "arnia.read", "Non hai accesso a questa arnia"
    )

    with db_operation("recupero arnia") as session:
        return arnie_service.get_arnia(session, id_arnia, current_user["id_utente"])


@app.put("/api/user/arnie/{id_arnia}", response_model=ArniaResponse, tags=["Utente"])
def update_arnia_user(
    id_arnia: int,
    arnia: ArniaUpdate,
    current_user: dict = Depends(get_current_active_user),
):
    """
    Aggiorna un'arnia (richiede permesso write o admin sull'arnia).
    Campi modificabili: nome, descrizione, posizione, coordinate, metadati.
    Non è possibile modificare attiva (usa admin per quello).
    """
    require_arnia_access(
        current_user, id_arnia, "arnia.update", "Permessi insufficienti su questa arnia"
    )
    # Retiring or reviving a hive is the owner's call; for anyone else
    # `attiva` is ignored, as it always was on this route.
    allow_attiva = check_user_arnia_access(
        current_user["id_utente"], id_arnia, "arnia.retire"
    )

    with db_operation("aggiornamento arnia") as session:
        return arnie_service.update_arnia(
            session, id_arnia, arnia, allow_attiva=allow_attiva
        )


@app.put("/api/user/password", response_model=MessageResponse, tags=["Utente"])
def change_own_password(
    body: PasswordChange, current_user: dict = Depends(get_current_active_user)
):
    """
    Cambia la propria password.
    """
    with db_operation("cambio password") as session:
        utenti_service.change_own_password(
            session, current_user["id_utente"], body.current_password, body.new_password
        )
    return {"message": "Password aggiornata con successo"}


@app.post("/api/admin/letture", response_model=LetturaResponse, tags=["Admin - Nodi"])
def create_lettura_manuale(
    lettura: LetturaCreate, current_user: dict = Depends(get_current_admin_user)
):
    """
    Inserisce una lettura manualmente (solo admin, utile per test e backfill).
    """
    with db_operation("inserimento lettura") as session:
        return letture_service.record_reading(session, lettura)


@app.patch(
    "/api/admin/letture/{id_lettura}",
    response_model=LetturaResponse,
    tags=["Admin - Nodi"],
)
def update_lettura(
    id_lettura: int,
    changes: LetturaUpdate,
    current_user: dict = Depends(get_current_admin_user),
):
    """
    Correct a reading (admin only): only the fields sent change, and a
    measurement sent as null is cleared. Hive and node stay as they are.
    """
    with db_operation("aggiornamento lettura") as session:
        return letture_service.update_lettura(session, id_lettura, changes)


@app.delete(
    "/api/admin/letture/{id_lettura}",
    response_model=MessageResponse,
    tags=["Admin - Nodi"],
)
def delete_lettura(
    id_lettura: int, current_user: dict = Depends(get_current_admin_user)
):
    """
    Delete one reading (admin only). Unlike nodes and hives, this is a real
    delete: a wrong reading has no history worth keeping.
    """
    with db_operation("eliminazione lettura") as session:
        letture_service.delete_lettura(session, id_lettura)
        return {"message": f"Lettura {id_lettura} eliminata"}


@app.post(
    "/api/admin/letture/elimina",
    response_model=MessageResponse,
    tags=["Admin - Nodi"],
)
def delete_letture(
    body: LettureDelete, current_user: dict = Depends(get_current_admin_user)
):
    """
    Delete readings by id, in bulk (admin only): pick them with the hive and
    date filters of `GET /api/user/arnie/{id_arnia}/letture`. Ids that do not
    exist are skipped; the message says how many were deleted.
    """
    with db_operation("eliminazione letture") as session:
        count = letture_service.delete_letture(session, body.id_letture)
        return {"message": f"{count} letture eliminate"}


# ============================================
# ENDPOINT INFO E HEALTH
# ============================================


@app.get("/", tags=["Info"])
def root():
    """Endpoint root con informazioni API"""
    return {
        "name": settings.API_TITLE,
        "version": settings.API_VERSION,
        "description": settings.API_DESCRIPTION,
        "docs_url": "/docs",
        "redoc_url": "/redoc",
    }


@app.get("/health", tags=["Info"])
def health_check():
    """Health check endpoint"""
    try:
        # Verifica connessione database
        with get_session() as session:
            ping(session)

        return {
            "status": "healthy",
            "database": "connected",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        # The reason goes to the log only. This endpoint is public, and a
        # connection error names the database host, port and user.
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "database": "disconnected",
            "timestamp": datetime.now().isoformat(),
        }


# ============================================
# ADMIN PAGE
# ============================================

# A static page that calls the admin routes above with the same bearer token
# as any client — it adds no route, no session and no logic of its own. It is
# its own component, at the repo root (admin/README.md); the API only serves it.
ADMIN_DIR = Path(__file__).resolve().parent.parent / "admin"

app.mount("/admin", StaticFiles(directory=ADMIN_DIR, html=True), name="admin")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
