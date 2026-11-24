"""Inscription des clients et droits RGPD (accès, portabilité, effacement).

Aucune donnée personnelle n'est écrite dans les journaux. Les fiches sont dans data/clients/ (hors Git).
L'export et la suppression demandent une session : celle du client concerné ou d'un compte équipe.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from src.onboarding import (DUREE_CONSERVATION_JOURS, NOTICE_VERSION, Inscription, InscriptionResultat, Registre,
                            gabarits)

router = APIRouter(prefix="/clients", tags=["clients"])


def _registre(request: Request) -> Registre:
    return Registre(request.app.state.service.data_dir)


def _geocoder(ville: str, pays: str) -> dict:
    from src.connectors.openmeteo import geocoder
    try:
        return geocoder(f"{ville}, {pays}")
    except Exception:
        try:
            return geocoder(ville)                # certains pays ne sont pas reconnus dans la requête
        except Exception as e:
            raise ValueError(f"lieu introuvable : « {ville}, {pays} »") from e


@router.get("/parametres")
def parametres() -> dict:
    """Gabarits sectoriels et version de la notice d'information à accepter."""
    return {"gabarits": gabarits(), "version_notice": NOTICE_VERSION,
            "conservation_annees": DUREE_CONSERVATION_JOURS // 365}


@router.post("/inscription", response_model=InscriptionResultat, status_code=201)
def inscription(ins: Inscription, request: Request) -> InscriptionResultat:
    """Crée l'espace d'un client : fiche de contact, topologie de sa chaîne et scénario modèle."""
    try:
        return _registre(request).inscrire(ins, _geocoder)
    except ValueError as e:                        # lieu introuvable ou chaîne incohérente (cycle, parts)
        raise HTTPException(status_code=422, detail=str(e))


def _autoriser(request: Request, client_id: str) -> None:
    session = getattr(request.state, "session", None)
    if session and session.get("role") != "equipe" and session.get("client_id") != client_id:
        raise HTTPException(status_code=403, detail="accès réservé au client concerné")


@router.get("/{client_id}/export")
def export(client_id: str, request: Request) -> dict:
    """Droit d'accès et de portabilité : données conservées pour ce client, au format JSON."""
    _autoriser(request, client_id)
    try:
        return _registre(request).exporter(client_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="client introuvable")


@router.delete("/{client_id}")
def suppression(client_id: str, request: Request) -> dict:
    """Droit à l'effacement : supprime la fiche, la topologie et le scénario du client."""
    _autoriser(request, client_id)
    try:
        return {"supprimes": _registre(request).supprimer(client_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="client introuvable")
