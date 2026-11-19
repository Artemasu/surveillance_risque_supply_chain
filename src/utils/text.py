"""Petites fonctions de texte reprises du notebook v2."""
from __future__ import annotations

import hashlib
import re
import unicodedata


def norm_key(s) -> str:
    """Clé de comparaison : minuscules, sans accents, espaces normalisés."""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def normalize_url(url) -> str:
    """Retire le protocole, 'www.', les paramètres de suivi et le slash final."""
    u = str(url).strip().lower()
    u = re.sub(r"^https?://(www\.)?", "", u)
    u = re.sub(r"[?#].*$", "", u)
    return u.rstrip("/")


def url_hash(url, n: int = 12) -> str:
    return hashlib.sha1(normalize_url(url).encode("utf-8")).hexdigest()[:n]


def contains_term(haystack_norm: str, term: str) -> bool:
    """Vrai si `term` apparaît comme mot entier dans un texte déjà normalisé par norm_key."""
    return bool(re.search(rf"(?<!\w){re.escape(norm_key(term))}(?!\w)", haystack_norm))
