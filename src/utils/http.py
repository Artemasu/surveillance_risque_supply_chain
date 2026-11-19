"""GET tolérant aux pannes, repris du notebook v2 (section 1.1) : délai maximal, essais, pauses croissantes."""
from __future__ import annotations

import logging
import time

import requests

from src.config import HTTP_HEADERS, settings

log = logging.getLogger("supplychain.http")


def http_get(url, params=None, timeout=None, retries=None, headers=None, info=None):
    """Renvoie la réponse, ou None après `retries` échecs. Ne lève jamais d'exception.

    info : dict optionnel, rempli avec la cause de l'échec ({"status": 404} ou {"error": "ConnectionError"}).
    429 et 5xx : pause croissante puis nouvel essai. 403, 404... : abandon immédiat, réessayer ne sert à rien.
    """
    info = {} if info is None else info
    timeout = timeout or settings.http_timeout_s
    retries = retries or settings.http_retries
    headers = {**HTTP_HEADERS, **(headers or {})}
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, params=params, timeout=timeout, headers=headers)
            info.update(status=r.status_code, error=None)
            if r.status_code == 200:
                return r
            if r.status_code == 429 or r.status_code >= 500:
                log.warning("HTTP %s sur %s (essai %s/%s)", r.status_code, url[:120], attempt, retries)
                time.sleep(3 * attempt if attempt < retries else 0)
                continue
            log.warning("HTTP %s sur %s : abandon", r.status_code, url[:120])
            return None
        except requests.RequestException as e:
            info.update(status=None, error=type(e).__name__)
            log.warning("réseau : %s sur %s (essai %s/%s)", type(e).__name__, url[:120], attempt, retries)
            time.sleep(1.5 * attempt if attempt < retries else 0)
    return None
