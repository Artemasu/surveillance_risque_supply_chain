"""Configuration centrale. Tout ce qui se règle est ici ou dans les variables d'environnement."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on", "oui"}


FALLBACK_LLM_MODEL = "qwen2.5:3b"     # meilleur compromis mesuré sur CPU (scripts/benchmark_ollama.py)


def _configured_llm_model() -> tuple[str, bool]:
    """Modèle LLM et indicateur « choisi automatiquement ».

    Ordre : OLLAMA_MODEL, puis LLM_MODEL (compatibilité), puis la recommandation du dernier benchmark local
    (data/cache/llm_benchmark.json, écrit par scripts/benchmark_ollama.py), puis qwen2.5:3b. Sans variable
    d'environnement, le modèle est « auto » : s'il n'est pas installé, src/utils/llm.py en choisit un parmi ceux
    d'Ollama (/api/tags)."""
    for var in ("OLLAMA_MODEL", "LLM_MODEL"):
        if os.getenv(var, "").strip():
            return os.environ[var].strip(), False
    bench = Path(os.getenv("SC_DATA_DIR", ROOT / "data")) / "cache" / "llm_benchmark.json"
    try:
        rec = json.loads(bench.read_text(encoding="utf-8")).get("recommended")
        if isinstance(rec, str) and rec.strip():
            return rec.strip(), True
    except (OSError, ValueError):
        pass
    return FALLBACK_LLM_MODEL, True


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("SC_DATA_DIR", ROOT / "data")))

    # --- LLM local (mêmes valeurs par défaut que le notebook v2) ---
    use_llm: bool = field(default_factory=lambda: _bool("USE_LLM", False))
    llm_backend: str = field(default_factory=lambda: os.getenv("LLM_BACKEND", "ollama"))  # "ollama" | "openai"
    llm_base_url: str = field(default_factory=lambda: os.getenv("LLM_BASE_URL", "http://localhost:11434"))
    llm_model: str = field(default_factory=lambda: _configured_llm_model()[0])
    llm_auto: bool = field(default_factory=lambda: _configured_llm_model()[1])   # True : repli sur les modèles installés
    llm_timeout_s: int = field(default_factory=lambda: int(os.getenv("LLM_TIMEOUT_S", "120")))      # copilot
    # Extraction médias sur CPU : seuls les N groupes d'articles les plus pertinents passent par le LLM, chacun avec un
    # délai strict, dans un budget global ; le reste est traité par la baseline NLP. L'analyse ne bloque jamais.
    llm_max_articles: int = field(default_factory=lambda: int(os.getenv("LLM_MAX_ARTICLES", "6")))
    llm_article_timeout_s: float = field(default_factory=lambda: float(os.getenv("LLM_ARTICLE_TIMEOUT_S", "15")))
    llm_budget_s: float = field(default_factory=lambda: float(os.getenv("LLM_BUDGET_S", "30")))
    llm_num_predict: int = field(default_factory=lambda: int(os.getenv("LLM_NUM_PREDICT", "512")))
    llm_api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))  # jamais écrite dans le code

    # Rattachement élargi des articles (matières premières, mots-clés sectoriels, pays), à confiance modérée :
    # "live" (par défaut : seulement en mode live), "always" (aussi en replay) ou "never".
    broad_linking: str = field(default_factory=lambda: os.getenv("BROAD_LINKING", "live").strip().lower())

    # --- Collecte live (notebook v2, section 0.3) ---
    lookback_days: int = 7
    gdelt_max: int = 100            # requête plus légère : 100 articles au lieu de 200 (250 maximum côté API)
    gdelt_retry_pause_s: int = 30
    http_timeout_s: int = 20
    http_retries: int = 2

    # --- Déduplication et classification (notebook v2) ---
    sim_threshold: float = 0.45
    window_hours: int = 72
    min_confidence: float = 0.35

    @property
    def topology_path(self) -> Path:
        """Topologie par défaut. SC_TOPOLOGY permet d'en choisir une autre (chemin absolu ou relatif à data/)."""
        custom = os.getenv("SC_TOPOLOGY")
        if custom:
            return Path(custom) if Path(custom).is_absolute() else self.data_dir / custom
        return self.data_dir / "topology.yaml"

    @property
    def cache_dir(self) -> Path:
        """Cache disque (réponses GDELT et Google News, fichiers GKG). SC_CACHE_DIR pour le déplacer."""
        return Path(os.getenv("SC_CACHE_DIR", self.data_dir / "cache"))

    @property
    def db_path(self) -> Path:
        """Base unifiée DuckDB (médias + météo + finance, historique des exécutions). SC_DB_PATH pour la déplacer."""
        return Path(os.getenv("SC_DB_PATH", self.data_dir / "aegis.duckdb"))

    @property
    def offline(self) -> bool:
        """SC_OFFLINE=1 : les connecteurs des volets Météo et Finance lisent seulement leur cache (tests, démo)."""
        return _bool("SC_OFFLINE", False)

    @property
    def persist_runs(self) -> bool:
        """Chaque exécution du pipeline est enregistrée dans la base (désactivable : SC_PERSIST=0)."""
        return _bool("SC_PERSIST", True)

    @property
    def scenario_dir(self) -> Path:
        return self.data_dir / "replay_scenarios"


settings = Settings()

# En-têtes de navigateur : plusieurs sites de presse renvoient 403 à un client qui s'annonce comme un script
HTTP_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/131.0.0.0 Safari/537.36"),
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}
