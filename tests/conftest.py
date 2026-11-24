import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("USE_LLM", "false")

from src.graph.ontology_engine import OntologyEngine  # noqa: E402
from src.schemas.events import (EntityRef, EventInfo, EventMeta, Location, MediaRef, NormalizedEvent,  # noqa: E402
                                PipelineRunRequest, WeatherBlock)
from src.service import SupplyChainService  # noqa: E402

SCENARIO = "crisis_asia_semiconductors"


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Chaque test a son propre cache disque : rien n'est écrit dans data/cache."""
    monkeypatch.setenv("SC_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SC_DB_PATH", str(tmp_path / "aegis.duckdb"))   # base unifiée isolée
    monkeypatch.setenv("SC_OFFLINE", "1")          # connecteurs météo/finance : cache seul, jamais le réseau
    monkeypatch.setenv("SC_AUTH", "0")             # comptes testés à part (tests/test_auth.py)


@pytest.fixture
def engine() -> OntologyEngine:
    return OntologyEngine.from_yaml(ROOT / "data" / "topology.yaml")


@pytest.fixture
def service() -> SupplyChainService:
    return SupplyChainService()


@pytest.fixture
def loaded_service(service) -> SupplyChainService:
    """Service après le scénario complet (jour 7)."""
    asyncio.run(service.run_pipeline(PipelineRunRequest(mode="replay", scenario=SCENARIO, day=7)))
    return service


def media_event(eid: str, etype: str, day: str, node_id: str, name: str, n_sources: int = 1, place=None) -> NormalizedEvent:
    return NormalizedEvent(
        event=EventInfo(id=eid, type=etype, label=f"{etype} sur {name}"), date=day, location=Location(name=place),
        entities=[EntityRef(id=f"SUP:{node_id}", name=name, role="touché")],
        media=[MediaRef(titre=f"article {i}", date=f"{day}T08:00:00Z", source_id=f"test:{eid}:{i}") for i in range(n_sources)],
        donnees_manquantes=["weather", "finance"], meta=EventMeta(agent="media", confidence=0.6, extractor="baseline"))


def weather_event(eid: str, day: str, node_id: str, name: str, gust: float = 180, rain: float = 300) -> NormalizedEvent:
    return NormalizedEvent(
        event=EventInfo(id=eid, type="meteo_extreme", label=f"tempête sur {name}"), date=day, location=Location(name=name),
        entities=[EntityRef(id=f"NODE:{node_id}", name=name, role="touché")],
        weather=WeatherBlock(hub=node_id, date=day, gust_max_kmh=gust, precip_mm=rain, source_id=f"test:meteo:{eid}"),
        meta=EventMeta(agent="weather", confidence=0.9, extractor="seuils"))
