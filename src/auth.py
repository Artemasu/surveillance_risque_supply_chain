"""Comptes et sessions : connexion par e-mail et mot de passe, jeton signé, routes protégées.

Deux sortes de comptes :
  - client : créé par l'inscription (src/onboarding.py), rattaché à sa topologie ;
  - équipe : créé en ligne de commande, accès à toutes les chaînes (démonstrations, administration).

    python -m src.auth creer-compte --email prenom.nom@exemple.fr --nom "Prénom Nom"

Sécurité : mots de passe hachés avec scrypt et un sel propre à chaque compte, jamais stockés ni journalisés en clair ;
jeton signé HMAC-SHA256 valable 8 heures ; cinq essais de connexion par adresse et par quart d'heure.
Les comptes et la clé de signature sont dans data/clients/ (hors Git).
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Optional

from src.config import settings

DUREE_SESSION_S = 8 * 3600
ESSAIS_MAX, FENETRE_ESSAIS_S = 5, 15 * 60
LONGUEUR_MIN_MDP = 12
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}

# Routes accessibles sans compte : page vitrine (santé du service), connexion, inscription, documentation.
ROUTES_PUBLIQUES = {"/health", "/auth/connexion", "/clients/parametres", "/clients/inscription",
                    "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}


def auth_active() -> bool:
    """SC_AUTH=0 désactive la protection (tests automatisés uniquement)."""
    return os.getenv("SC_AUTH", "1").strip().lower() not in {"0", "false", "non", "off"}


def dossier_comptes(data_dir: Optional[Path] = None) -> Path:
    return Path(data_dir or settings.data_dir) / "clients"


# --------------------------------------------------------------------------- périmètre d'un compte client
def topologie_autorisee(session: Optional[dict], ref: Optional[str]) -> bool:
    """Un client voit sa chaîne et les chaînes de démonstration, jamais celles des autres clients.
    session None : protection désactivée (tests). Compte équipe : tout."""
    if session is None or session.get("role") == "equipe":
        return True
    return not Path(ref or "topology.yaml").name.startswith("client_") or ref == session.get("topology_ref")


def scenario_autorise(session: Optional[dict], scenario_id: Optional[str]) -> bool:
    if session is None or session.get("role") == "equipe" or not (scenario_id or "").startswith("client_"):
        return True
    return scenario_id.startswith(f"client_{session.get('client_id')}_")


# Routes qui montrent la dernière analyse : un client n'y accède que si elle porte sur une chaîne qu'il peut voir.
ROUTES_ETAT = ("/graph", "/alerts", "/events", "/chat")
ROUTES_EQUIPE = ("/database", "/jobs")          # explorateur de toute la base, collectes : comptes équipe


# --------------------------------------------------------------------------- mots de passe
def verifier_robustesse(mdp: str) -> None:
    if len(mdp) < LONGUEUR_MIN_MDP:
        raise ValueError(f"le mot de passe doit contenir au moins {LONGUEUR_MIN_MDP} caractères")
    if mdp.isalpha() or mdp.isdigit():
        raise ValueError("le mot de passe doit mêler lettres et chiffres ou symboles")


def hacher(mdp: str) -> dict:
    sel = secrets.token_bytes(16)
    empreinte = hashlib.scrypt(mdp.encode(), salt=sel, **_SCRYPT)
    return {"algo": "scrypt", "sel": sel.hex(), "empreinte": empreinte.hex()}


def mdp_correct(mdp: str, stocke: dict) -> bool:
    calcule = hashlib.scrypt(mdp.encode(), salt=bytes.fromhex(stocke["sel"]), **_SCRYPT)
    return hmac.compare_digest(calcule.hex(), stocke["empreinte"])


# --------------------------------------------------------------------------- jetons
def _cle(data_dir: Optional[Path] = None) -> bytes:
    """Clé de signature : AEGIS_SECRET, sinon générée une fois et conservée dans data/clients/ (hors Git)."""
    if os.getenv("AEGIS_SECRET"):
        return os.environ["AEGIS_SECRET"].encode()
    chemin = dossier_comptes(data_dir) / ".cle_session"
    if not chemin.exists():
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(secrets.token_hex(32), encoding="utf-8")
    return chemin.read_text(encoding="utf-8").strip().encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def creer_jeton(session: dict, data_dir: Optional[Path] = None) -> str:
    corps = _b64(json.dumps({**session, "exp": int(time.time()) + DUREE_SESSION_S}).encode())
    signature = _b64(hmac.new(_cle(data_dir), corps.encode(), hashlib.sha256).digest())
    return f"{corps}.{signature}"


def lire_jeton(jeton: str, data_dir: Optional[Path] = None) -> Optional[dict]:
    try:
        corps, signature = jeton.split(".")
        attendu = _b64(hmac.new(_cle(data_dir), corps.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, attendu):
            return None
        session = json.loads(base64.urlsafe_b64decode(corps + "=" * (-len(corps) % 4)))
        return session if session.get("exp", 0) > time.time() else None
    except (ValueError, KeyError, TypeError):
        return None


# --------------------------------------------------------------------------- comptes
def _fichier_equipe(data_dir: Optional[Path] = None) -> Path:
    return dossier_comptes(data_dir) / "comptes_equipe.json"


def comptes_equipe(data_dir: Optional[Path] = None) -> dict:
    f = _fichier_equipe(data_dir)
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def email_utilise(email: str, data_dir: Optional[Path] = None) -> bool:
    return _trouver(email.lower(), data_dir) is not None


def _trouver(email: str, data_dir: Optional[Path] = None) -> Optional[dict]:
    """Compte correspondant à l'adresse : équipe d'abord, puis fiches clients."""
    equipe = comptes_equipe(data_dir).get(email)
    if equipe:
        return {"role": "equipe", "email": email, "nom": equipe["nom"], "mdp": equipe["mdp"], "topology_ref": None,
                "client_id": None, "societe": None}
    for fiche in dossier_comptes(data_dir).glob("*.json"):
        if fiche.name == _fichier_equipe(data_dir).name:
            continue
        try:
            f = json.loads(fiche.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if f.get("contact", {}).get("email") == email and "authentification" in f:
            return {"role": "client", "email": email, "nom": f"{f['contact']['prenom']} {f['contact']['nom']}",
                    "mdp": f["authentification"], "topology_ref": f.get("topologie"), "client_id": f["client_id"],
                    "societe": f["entreprise"]["raison_sociale"]}
    return None


_essais: dict[str, deque] = defaultdict(deque)


def connecter(email: str, mdp: str, data_dir: Optional[Path] = None) -> tuple[str, dict]:
    """Renvoie (jeton, profil). Erreur volontairement identique pour une adresse inconnue ou un mauvais mot de passe."""
    email = email.strip().lower()
    maintenant, essais = time.time(), _essais[email]
    while essais and essais[0] < maintenant - FENETRE_ESSAIS_S:
        essais.popleft()
    if len(essais) >= ESSAIS_MAX:
        raise PermissionError("trop de tentatives : réessayez dans quelques minutes")
    compte = _trouver(email, data_dir)
    if compte is None or not mdp_correct(mdp, compte["mdp"]):
        essais.append(maintenant)
        raise PermissionError("adresse e-mail ou mot de passe incorrect")
    essais.clear()
    profil = {k: compte[k] for k in ("role", "email", "nom", "topology_ref", "client_id", "societe")}
    return creer_jeton(profil, data_dir), profil


def creer_compte_equipe(email: str, nom: str, mdp: str, data_dir: Optional[Path] = None) -> None:
    verifier_robustesse(mdp)
    comptes = comptes_equipe(data_dir)
    comptes[email.strip().lower()] = {"nom": nom, "mdp": hacher(mdp)}
    f = _fichier_equipe(data_dir)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(comptes, ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Comptes de l'équipe A.E.G.I.S.")
    sous = ap.add_subparsers(dest="commande", required=True)
    c = sous.add_parser("creer-compte", help="créer ou réinitialiser un compte équipe (accès à toutes les chaînes)")
    c.add_argument("--email", required=True)
    c.add_argument("--nom", required=True)
    a = ap.parse_args(argv)
    mdp = getpass.getpass(f"Mot de passe ({LONGUEUR_MIN_MDP} caractères minimum) : ")
    if getpass.getpass("Confirmation : ") != mdp:
        print("Les deux saisies diffèrent.")
        return 1
    try:
        creer_compte_equipe(a.email, a.nom, mdp)
    except ValueError as e:
        print(f"Refusé : {e}")
        return 1
    print(f"Compte équipe prêt : {a.email.lower()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
