"""Autres secteurs : générateur de configuration, second scénario, changement de topologie, figures."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from scripts import generate_sector_config as gen
from src.api.main import create_app
from src.graph.ontology_engine import OntologyEngine
from src.schemas.events import ChatRequest, PipelineRunRequest
from src.service import ScenarioNotFound, SupplyChainService
from tests.conftest import ROOT, SCENARIO

PHARMA = "crisis_pharma_api"


def run(service, scenario, day=None):
    return asyncio.run(service.run_pipeline(PipelineRunRequest(mode="replay", scenario=scenario, day=day)))


# ----------------------------------------------------------------------------- générateur
@pytest.mark.parametrize("sector", sorted(gen.PRESETS))
def test_every_preset_is_a_valid_topology(sector):
    engine = OntologyEngine(gen.build_topology(sector, "Acme Santé"))
    types = {n.type for n in engine.nodes.values()}
    assert {"fournisseur", "port", "usine", "produit_fini"} <= types
    assert any("Acme" in n.name for n in engine.nodes.values()), "le nom de l'entreprise apparaît dans la topologie"
    assert not any("{" in n.name or any("{" in a for a in n.aliases) for n in engine.nodes.values())
    assert engine.weather_hubs() and engine.market_watch


def test_cli_writes_topology_and_runnable_scenario(tmp_path, capsys):
    (tmp_path / "replay_scenarios").mkdir()
    code = gen.main(["--sector", "generique", "--company", "Ma PME", "--name", "Ma PME test", "--days", "4",
                     "--start-date", "2026-03-02", "--data-dir", str(tmp_path)])
    assert code == 0
    topo, scen = tmp_path / "topologies" / "ma_pme_test.yaml", tmp_path / "replay_scenarios" / "ma_pme_test_modele.json"
    assert topo.exists() and scen.exists() and "ma_pme_test.yaml" in capsys.readouterr().out
    assert topo.read_text(encoding="utf-8").startswith("# Topologie générée")
    meta = json.loads(scen.read_text(encoding="utf-8"))["meta"]
    assert meta["topology"] == "topologies/ma_pme_test.yaml" and meta["days"] == 4 and meta["start_date"] == "2026-03-02"

    service = SupplyChainService(topology_path=ROOT / "data" / "topology.yaml", scenario_dir=tmp_path / "replay_scenarios")
    res = run(service, "ma_pme_test_modele")
    assert res.status == "success" and res.n_events == 0 and res.n_alerts == 0 and res.global_risk_index == 0
    assert len(service.engine.nodes) == 9 and any(n.name.startswith("Ma (usine") for n in service.engine.nodes.values())
    assert service.engine.simulate_disruption("port_depart", 1.0).threatened_products, "la simulation marche sur la nouvelle chaîne"


def test_cli_refuses_to_overwrite_and_validates_arguments(tmp_path):
    args = ["--sector", "pharma", "--company", "Helvia Pharma", "--data-dir", str(tmp_path), "--no-scenario"]
    assert gen.main(args) == 0
    assert not (tmp_path / "replay_scenarios").exists(), "--no-scenario n'écrit que la topologie"
    assert gen.main(args) == 1, "pas d'écrasement sans --force"
    assert gen.main(args + ["--force"]) == 0
    assert gen.main(["--list"]) == 0
    for bad in (["--company", "X"], ["--sector", "nucleaire"], ["--sector", "pharma", "--start-date", "demain"],
                ["--sector", "pharma", "--days", "0"]):
        with pytest.raises(SystemExit):
            gen.main(bad + ["--data-dir", str(tmp_path)])


def test_cli_check_reports_valid_and_invalid_topologies(tmp_path, capsys):
    assert gen.main(["--check", str(ROOT / "data" / "topology.yaml")]) == 0
    out = capsys.readouterr().out
    assert "VALIDE" in out and "source unique" in out and "Kansai Drive dépend de « Baotou Magnetics »" in out
    bad = tmp_path / "bad.yaml"
    bad.write_text("nodes:\n  - {id: a, name: A, type: usine, tier: 1, criticality: 0.5}\n"
                   "edges:\n  - {source: a, target: zzz, input: x, dependency: 1.0}\n", encoding="utf-8")
    assert gen.main(["--check", str(bad)]) == 1 and "INVALIDE" in capsys.readouterr().out


def test_shipped_pharma_topology_matches_its_preset():
    shipped = OntologyEngine.from_yaml(ROOT / "data" / "topologies" / "pharma_helvia.yaml")
    preset = OntologyEngine(gen.build_topology("pharma", "Helvia Pharma"))
    assert set(shipped.nodes) == set(preset.nodes) and len(shipped.edges) == len(preset.edges)


# ----------------------------------------------------------------------------- second scénario
def test_pharma_scenario_runs_on_its_own_topology(service):
    assert len(service.engine.nodes) == 30
    sc = {s["id"]: s for s in service.list_scenarios()}
    assert sc[PHARMA]["topology"] == "topologies/pharma_helvia.yaml" and sc[SCENARIO]["topology"] == "topology.yaml"
    res = run(service, PHARMA)
    assert res.status == "success" and res.fictional and res.days_total == 6 and res.as_of == "2026-07-11"
    assert len(service.engine.nodes) == 19 and "sup_api_in" in service.engine.nodes
    nodes = {n.id: n for n in service.engine.state().nodes}
    for node in ("sup_api_in", "port_antwerp", "plant_ff_fr", "prod_antibio_inj"):
        assert nodes[node].level == "critical", node
    assert nodes["sup_api_it"].level == "ok" and nodes["sup_vials_de"].level == "ok"
    types = {e.event.type for e in service.engine.events}
    assert {"sanction", "catastrophe", "cyberattaque", "penurie", "meteo_extreme", "tension_marche"} <= types
    index = [p.global_risk_index for p in res.timeline]
    assert len(index) == 6 and index[0] < index[2] < index[-1]


def test_pharma_early_warning(service):
    run(service, PHARMA, day=2)
    plant = {n.id: n for n in service.engine.state().nodes}["plant_ff_fr"]
    assert plant.level == "warning" and plant.direct == 0 and plant.path[0] == "sup_api_in"
    run(service, PHARMA, day=6)
    assert {n.id: n for n in service.engine.state().nodes}["plant_ff_fr"].direct > 0


def test_switching_scenarios_switches_topology_and_copilot(service):
    run(service, PHARMA)
    answer = service.chat(ChatRequest(message="Que se passe-t-il si le port d'Anvers est bloqué à 80 % ?"), use_llm=False)
    assert answer.tool_calls[0].result["noeud_id"] == "port_antwerp" and "Helvia Tours" in answer.answer
    assert "erreur" in service.assistant.run_tool("simuler_perturbation", {"noeud": "port de Kaohsiung", "gravite": 0.8})
    run(service, SCENARIO)
    assert len(service.engine.nodes) == 30 and "port_kaohsiung" in service.engine.nodes
    back = service.chat(ChatRequest(message="Simule une fermeture du port de Rotterdam"), use_llm=False)
    assert back.tool_calls[0].result["noeud_id"] == "port_rotterdam"


def test_live_mode_goes_back_to_default_topology(service, monkeypatch):
    run(service, PHARMA)
    for agent in service.agents.values():
        monkeypatch.setattr(type(agent), "collect_live", lambda self, report=None, **k: _failed(report, self.name))
    res = asyncio.run(service.run_pipeline(PipelineRunRequest(mode="live")))
    assert res.status == "error" and len(service.engine.nodes) == 30


async def _failed(report, name):
    report[name] = {"status": "failed"}
    return []


def test_scenario_topology_must_stay_inside_data_dir(service):
    for ref in ("../README.md", "../../etc/passwd", "topologies/absente.yaml", "replay_scenarios/crisis_pharma_api.json"):
        with pytest.raises(ScenarioNotFound):
            service.resolve_topology(ref)
    assert service.resolve_topology(None) == service.default_topology


def test_api_follows_topology_switch():
    client = TestClient(create_app(SupplyChainService()))
    assert client.get("/health").json()["nodes"] == 30
    body = client.post("/pipeline/run", json={"mode": "replay", "scenario": PHARMA, "day": 4}).json()
    assert body["status"] == "success" and body["as_of"] == "2026-07-09"
    state = client.get("/graph/state").json()
    assert len(state["nodes"]) == 19 and "port_antwerp" in state["critical_nodes"]
    assert client.post("/graph/simulate", json={"node_id": "port_kaohsiung", "severity": 0.5}).status_code == 404
    assert client.post("/graph/simulate", json={"node_id": "port_antwerp", "severity": 1.0}).status_code == 200
    assert {s["id"] for s in client.get("/scenarios").json()} >= {SCENARIO, PHARMA}


def test_topology_override_by_environment(monkeypatch):
    monkeypatch.setenv("SC_TOPOLOGY", "topologies/pharma_helvia.yaml")
    assert len(SupplyChainService().engine.nodes) == 19


# ----------------------------------------------------------------------------- figures de soutenance
def test_export_soutenance_figures(tmp_path, capsys):
    pytest.importorskip("matplotlib")
    from scripts import export_soutenance
    assert export_soutenance.main(["--out", str(tmp_path), "--dpi", "60"]) == 0
    out = capsys.readouterr().out
    for name in ("indice_global_crisis_asia_semiconductors.png", "anticipation_plant_ecu_de.png"):
        path = tmp_path / name
        assert path.exists() and path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and path.stat().st_size > 10_000
    assert "J1 6.0" in out and "J7 40.6" in out
    assert "première alerte J2, premier article J6, avance 4 jour(s)" in out


def test_export_soutenance_facts_come_from_the_replay():
    from scripts.export_soutenance import replay
    data = replay(SCENARIO, "plant_ecu_de")
    rows = {r["day"]: r for r in data["rows"]}
    assert [r["articles"] > 0 for r in data["rows"]] == [False] * 5 + [True, True]
    assert rows[1]["risk"] < 35 <= rows[2]["risk"] and rows[2]["direct"] == 0 and rows[6]["direct"] > 0
    assert data["names"][rows[2]["origin"]] == "Port of Kaohsiung"
