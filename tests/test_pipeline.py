"""Pipeline complet sur le scénario de crise : cascade, alerte précoce, absence de fuite du futur."""
import asyncio

import pytest

from src.schemas.events import PipelineRunRequest
from src.service import ScenarioNotFound
from tests.conftest import SCENARIO


def run_day(service, day):
    return asyncio.run(service.run_pipeline(PipelineRunRequest(mode="replay", scenario=SCENARIO, day=day)))


def test_scenario_is_listed_and_flagged_fictional(service):
    sc = {s["id"]: s for s in service.list_scenarios()}[SCENARIO]
    assert sc["fictional"] and sc["days"] == 7 and len(sc["storyline"]) == 7


def test_crisis_builds_up_over_seven_days(service):
    res = run_day(service, 7)
    assert res.status == "success" and res.fictional and res.as_of == "2026-09-20"
    assert set(res.agents) == {"media", "weather", "finance"} and all(a.status == "success" for a in res.agents.values())
    index = [p.global_risk_index for p in res.timeline]
    assert len(index) == 7 and index == sorted(index), "l'indice monte tout au long de la crise"
    assert index[0] < 15 < index[2] and res.global_risk_index == index[-1]
    risks = {n.id: n for n in service.engine.state().nodes}
    for node in ("port_kaohsiung", "sup_chip_tw", "port_rotterdam", "plant_ecu_de", "plant_assembly_fr", "prod_ev_compact"):
        assert risks[node].level == "critical", node
    assert risks["rm_lithium"].level == "ok" and risks["plant_pack_fr"].level == "ok", "la filière batterie n'est pas touchée"


def test_early_warning_before_media_confirmation(service):
    """L'usine de Stuttgart passe en alerte par propagation dès le jour 2 ; le premier article qui la cite est au jour 6."""
    run_day(service, 1)
    assert {n.id: n for n in service.engine.state().nodes}["plant_ecu_de"].level == "ok"
    run_day(service, 2)
    early = {n.id: n for n in service.engine.state().nodes}["plant_ecu_de"]
    assert early.level == "warning" and early.direct == 0
    run_day(service, 5)
    assert {n.id: n for n in service.engine.state().nodes}["plant_ecu_de"].direct == 0
    run_day(service, 3)
    plant = {n.id: n for n in service.engine.state().nodes}["plant_ecu_de"]
    assert plant.level in {"warning", "critical"} and plant.direct == 0 and plant.path[0] == "port_kaohsiung"
    alert = next(a for a in service.engine.alerts() if a.node_id == "plant_ecu_de")
    assert set(alert.agents) >= {"media", "weather"}
    run_day(service, 6)
    assert {n.id: n for n in service.engine.state().nodes}["plant_ecu_de"].direct > 0


def test_day_one_is_a_weak_signal(service):
    res = run_day(service, 1)
    assert res.n_alerts == 0 and 0 < res.global_risk_index < 15
    payload = service.events_payload()
    unlinked = [e for e in payload["events"] if e["agent"] == "media" and not e["nodes"]]
    assert unlinked, "l'article sur le typhon est détecté mais pas encore rattaché à un nœud"


def test_timeline_has_no_future_leak(service):
    full = {p.date: p.global_risk_index for p in run_day(service, 7).timeline}
    for day in (2, 4):
        partial = run_day(service, day)
        assert partial.timeline[-1].global_risk_index == full[partial.as_of]


def test_cross_validation_fills_weather_block(loaded_service):
    events = [e for e in loaded_service.engine.events if e.meta.agent == "media"]
    landfall = next(e for e in events if any(m.source_id.endswith("004") for m in e.media))
    assert landfall.weather is not None and landfall.weather.hub == "port_kaohsiung"
    assert "weather" not in landfall.donnees_manquantes
    strike = next(e for e in events if e.event.type == "greve")
    assert strike.weather is None and "weather" in strike.donnees_manquantes
    corroborated = [s for s in loaded_service.engine.current.signals if s.corroborated]
    assert {s.node_id for s in corroborated} >= {"port_kaohsiung", "sup_chip_tw"}


def test_unknown_scenario(service):
    with pytest.raises(ScenarioNotFound):
        asyncio.run(service.run_pipeline(PipelineRunRequest(mode="replay", scenario="inconnu")))
    with pytest.raises(ScenarioNotFound):
        service.load_scenario("../../etc/passwd")


def test_live_outage_keeps_previous_state(loaded_service, monkeypatch):
    """Tous les agents en panne : status=error, l'état précédent reste en place, rien n'est inventé."""
    before = loaded_service.engine.current.index
    for agent in loaded_service.agents.values():
        async def nothing(report=None, _name=agent.name, **k):
            report[_name] = {"status": "failed"}
            return []
        monkeypatch.setattr(agent, "collect_live", nothing)
    res = asyncio.run(loaded_service.run_pipeline(PipelineRunRequest(mode="live")))
    assert res.status == "error" and res.degraded and "pas une absence d'alerte" in res.message
    assert all(a.error_type == "network_failure" for a in res.agents.values())
    assert loaded_service.engine.current.index == before and loaded_service.engine.mode.startswith("replay")


def test_live_partial_outage_is_flagged(service, monkeypatch):
    async def storm(report=None, **k):
        report["open_meteo"] = {"status": "ok"}
        return [{"node_id": "port_rotterdam", "date": "2026-11-16", "issued": "2026-11-16", "gust_max_kmh": 150,
                 "wind_max_kmh": 100, "precip_mm": 80, "source_id": "openmeteo:port_rotterdam:2026-11-16"}]
    monkeypatch.setattr(service.agents["weather"], "collect_live", storm)
    for name in ("media", "finance"):
        async def nothing(report=None, _name=name, **k):
            report[_name] = {"status": "failed"}
            return []
        monkeypatch.setattr(service.agents[name], "collect_live", nothing)
    res = asyncio.run(service.run_pipeline(PipelineRunRequest(mode="live")))
    assert res.status == "partial" and res.degraded and not res.fictional and "media" in res.message
    assert res.n_events == 1 and service.engine.mode == "live"
    assert {n.id: n for n in service.engine.state().nodes}["port_rotterdam"].direct > 0
