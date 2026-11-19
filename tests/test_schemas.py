"""Validation Pydantic du contrat commun."""
import pytest
from pydantic import ValidationError

from src.schemas.events import (EventInfo, EventMeta, FinanceBlock, GraphEdge, GraphNode, Location, MediaRef,
                                NormalizedEvent, PipelineRunRequest, SimulationRequest)
from tests.conftest import media_event, weather_event


def test_valid_media_event_round_trip():
    ev = media_event("evt_0001", "greve", "2026-09-17", "port_rotterdam", "Port of Rotterdam", n_sources=2)
    again = NormalizedEvent.model_validate_json(ev.model_dump_json())
    assert again == ev
    assert list(ev.model_dump()) == ["event", "date", "location", "entities", "weather", "finance", "media",
                                     "donnees_manquantes", "meta"]
    assert ev.source_ids == ["test:evt_0001:0", "test:evt_0001:1"]


def test_unknown_key_is_rejected():
    data = media_event("e", "greve", "2026-09-17", "n", "N").model_dump()
    data["severity"] = 0.9                       # l'agent ne calcule pas de gravité : la clé n'existe pas
    with pytest.raises(ValidationError):
        NormalizedEvent(**data)


@pytest.mark.parametrize("field, value", [("type", "invasion"), ("label", "   "), ("id", "")])
def test_event_info_rejects_bad_values(field, value):
    data = {"id": "evt_1", "type": "greve", "label": "ok", field: value}
    with pytest.raises(ValidationError):
        EventInfo(**data)


@pytest.mark.parametrize("bad", ["17/09/2026", "2026-9-17", "hier"])
def test_date_must_be_iso(bad):
    data = media_event("e", "greve", "2026-09-17", "n", "N").model_dump()
    data["date"] = bad
    with pytest.raises(ValidationError):
        NormalizedEvent(**data)


def test_no_fact_without_source():
    meta = EventMeta(agent="media", confidence=0.5, extractor="baseline")
    with pytest.raises(ValidationError, match="au moins un article"):
        NormalizedEvent(event=EventInfo(id="e", type="greve", label="x"), location=Location(), media=[], meta=meta)
    with pytest.raises(ValidationError, match="bloc weather"):
        NormalizedEvent(event=EventInfo(id="e", type="meteo_extreme", label="x"), location=Location(),
                        meta=EventMeta(agent="weather", confidence=0.9, extractor="seuils"))
    with pytest.raises(ValidationError, match="bloc finance"):
        NormalizedEvent(event=EventInfo(id="e", type="tension_marche", label="x"), location=Location(),
                        meta=EventMeta(agent="finance", confidence=0.8, extractor="seuils"))


def test_bounds():
    with pytest.raises(ValidationError):
        Location(name="x", lat=120.0, lon=0.0)
    with pytest.raises(ValidationError):
        EventMeta(agent="media", confidence=1.4, extractor="baseline")
    with pytest.raises(ValidationError):
        MediaRef(titre="t", source_id="")
    with pytest.raises(ValidationError):
        FinanceBlock(instrument="X", name="x", date="2026-01-01", close="cher", change_5d_pct=1.0, source_id="s")


def test_graph_models():
    GraphNode(id="n", name="N", type="port", tier=2, criticality=0.5)
    with pytest.raises(ValidationError):
        GraphNode(id="n", name="N", type="entrepot", tier=2, criticality=0.5)
    with pytest.raises(ValidationError):
        GraphEdge(source="a", target="b", input="x", dependency=1.5)


@pytest.mark.parametrize("severity", [-0.1, 1.01])
def test_simulation_request_bounds(severity):
    with pytest.raises(ValidationError):
        SimulationRequest(node_id="port_rotterdam", severity=severity)


def test_pipeline_request():
    assert PipelineRunRequest().mode == "replay"
    with pytest.raises(ValidationError):
        PipelineRunRequest(mode="demo")
    with pytest.raises(ValidationError):
        PipelineRunRequest(mode="replay", day=0)


def test_weather_event_helper_is_valid():
    assert weather_event("wx", "2026-09-16", "port_kaohsiung", "Port of Kaohsiung").weather.gust_max_kmh == 180
