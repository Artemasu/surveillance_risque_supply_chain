"""Connexion et protection des routes de l'API."""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from src.auth import (ROUTES_EQUIPE, ROUTES_ETAT, ROUTES_PUBLIQUES, auth_active, connecter, lire_jeton,
                      topologie_autorisee)

router = APIRouter(prefix="/auth", tags=["connexion"])


class Identifiants(BaseModel):
    email: str = Field(max_length=120)
    mot_de_passe: str = Field(max_length=200)


@router.post("/connexion")
def connexion(body: Identifiants, request: Request) -> dict:
    """Ouvre une session de 8 heures. Le jeton se passe ensuite dans l'en-tête `Authorization: Bearer <jeton>`."""
    try:
        jeton, profil = connecter(body.email, body.mot_de_passe, request.app.state.service.data_dir)
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))
    return {"jeton": jeton, "profil": profil}


@router.get("/moi")
def moi(request: Request) -> dict:
    """Profil de la session en cours."""
    return getattr(request.state, "session", None) or {}


class ProtectionMiddleware(BaseHTTPMiddleware):
    """Refuse toute route non publique sans jeton valide (401) et limite un compte client à son périmètre."""

    async def dispatch(self, request: Request, call_next):
        request.state.session = None
        if not auth_active() or request.method == "OPTIONS":
            return await call_next(request)
        service, path = request.app.state.service, request.url.path
        entete = request.headers.get("authorization", "")
        session = lire_jeton(entete[7:], service.data_dir) if entete.lower().startswith("bearer ") else None
        request.state.session = session
        if path in ROUTES_PUBLIQUES:
            return await call_next(request)
        if session is None:
            return JSONResponse({"detail": "connexion requise"}, status_code=401)
        if session.get("role") != "equipe":
            if path.startswith(ROUTES_EQUIPE):
                return JSONResponse({"detail": "réservé à l'équipe A.E.G.I.S."}, status_code=403)
            if path.startswith(ROUTES_ETAT) and not topologie_autorisee(session, service.topology_ref()):
                return JSONResponse({"detail": "aucune analyse de votre chaîne en cours : lancez l'analyse"},
                                    status_code=409)
            if path.startswith("/history"):          # l'historique d'un client se limite à sa propre chaîne
                params = [(k, v) for k, v in parse_qsl(request.url.query) if k != "topology"]
                params.append(("topology", session.get("topology_ref") or "topology.yaml"))
                request.scope["query_string"] = urlencode(params).encode()
        return await call_next(request)
