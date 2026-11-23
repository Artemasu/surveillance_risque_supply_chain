"""GET avec cache disque, partagé par tous les connecteurs.

Unifie `appel_api` (volet Météo) et `telecharger` (volet Finance) :
  - un sous-dossier par source (`<cache>/<namespace>/`), donc aucune collision de noms entre volets ;
  - une durée de vie par appel (`ttl_days`) : None = données historiques figées, jamais périmées ;
    une prévision ou un cours du jour expire au bout de quelques heures ;
  - 429 : pause croissante puis nouvel essai ; panne réseau : on renvoie l'ancienne copie plutôt que rien.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

import requests

from src.config import settings

log = logging.getLogger("supplychain.connectors")

USER_AGENT = "aegis-supply-chain (projet etudiant ESME)"
_SESSION = requests.Session()
_SESSION.headers["User-Agent"] = USER_AGENT


class SourceError(RuntimeError):
    """Erreur de collecte, avec un message lisible (source injoignable, format inattendu...)."""


def cache_dir(namespace: str) -> Path:
    d = settings.cache_dir / namespace
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_key(url: str, params: Optional[dict]) -> str:
    return hashlib.md5((url + json.dumps(params or {}, sort_keys=True, default=str)).encode()).hexdigest()


def _fresh(path: Path, ttl_days: Optional[float]) -> bool:
    if not path.exists():
        return False
    return ttl_days is None or (time.time() - path.stat().st_mtime) / 86400 < ttl_days


def fetch_bytes(url: str, params: Optional[dict] = None, *, namespace: str, ext: str = "bin",
                ttl_days: Optional[float] = 1, pause: float = 0.3, retries: int = 4, timeout: int = 90,
                offline: Optional[bool] = None) -> bytes:
    """Contenu brut d'une URL. Hors ligne (`offline` ou SC_OFFLINE=1) : lit seulement le cache."""
    offline = settings.offline if offline is None else offline
    path = cache_dir(namespace) / f"{cache_key(url, params)}.{ext}"
    if _fresh(path, ttl_days):
        return path.read_bytes()
    if offline:
        if path.exists():
            return path.read_bytes()
        raise SourceError(f"hors ligne et absent du cache : {url}")
    last = None
    for attempt in range(retries):
        try:
            r = _SESSION.get(url, params=params, timeout=timeout)
        except requests.RequestException as e:
            last = f"{type(e).__name__}"
            time.sleep(pause * (2 ** attempt))
            continue
        if r.status_code == 429:
            last = "HTTP 429 (limite de requêtes)"
            time.sleep(min(60, 5 * (attempt + 1)))
            continue
        if r.status_code != 200:
            last = f"HTTP {r.status_code}"
            if r.status_code < 500:
                break
            time.sleep(pause * (2 ** attempt))
            continue
        path.write_bytes(r.content)
        if pause:
            time.sleep(pause)
        return r.content
    if path.exists():                                  # réseau en panne : l'ancienne copie vaut mieux que rien
        log.warning("source injoignable (%s), copie en cache utilisée : %s", last, url[:100])
        return path.read_bytes()
    raise SourceError(f"téléchargement impossible ({last}) : {url[:160]}")


def fetch_json(url: str, params: Optional[dict] = None, *, namespace: str, ttl_days: Optional[float] = 1,
               **kw: Any) -> Any:
    raw = fetch_bytes(url, params, namespace=namespace, ext="json", ttl_days=ttl_days, **kw)
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise SourceError(f"réponse JSON illisible : {url[:120]}") from e
    if isinstance(data, dict) and data.get("error") is True:
        (cache_dir(namespace) / f"{cache_key(url, params)}.json").unlink(missing_ok=True)   # une erreur ne se garde pas
        raise SourceError(f"erreur API : {data.get('reason', data)}")
    return data
