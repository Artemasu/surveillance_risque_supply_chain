"""Volets Météo et Finance : méthode commune, agents calibrés, base unifiée, endpoints, stress tests."""
import asyncio
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from src.analytics import thresholds as th
from src.analytics.weather_indicators import add_indicators, calibrate_site, evaluate_site
from src.api.main import create_app
from src.graph.ontology_engine import OntologyEngine, event_intensity
from src.schemas.events import PipelineRunRequest
from src.service import SupplyChainService
from src.storage import db
from tests.conftest import ROOT, SCENARIO, weather_event

NOTEBOOKS = ROOT / "surveillance_risque_supply_chain-main"


def run(coro):
    return asyncio.run(coro)


def synthetic_history(seed=0, start="2010-01-01", end=None):
    rng = np.random.default_rng(seed)
    days = pd.date_range(start, end or date.today() - timedelta(days=8), freq="D")
    return pd.DataFrame({"date": days, "precipitation_sum": rng.gamma(0.6, 4, len(days)),
                         "wind_gusts_10m_max": rng.normal(45, 10, len(days)).clip(5),
                         "temperature_2m_max": rng.normal(18, 6, len(days)), "temperature_2m_min": rng.normal(8, 5, len(days)),
                         "snowfall_sum": np.zeros(len(days))})


# ----------------------------------------------------------------------------- méthode commune
def test_threshold_rank_and_episodes():
    calib = pd.Series(np.arange(1, 1001, dtype=float))
    assert th.threshold(calib, "haut", 0.99) == pytest.approx(990.01)
    assert th.threshold(calib, "bas", 0.99) == pytest.approx(10.99)
    assert th.rank_of(995, calib, "haut") == pytest.approx(0.994) and th.rank_of(5, calib, "bas") == pytest.approx(0.995)
    flags = pd.Series([True, True, False, False, True], index=pd.date_range("2024-01-01", periods=5))
    assert len(th.episodes(flags, ecart_max=1)) == 2 and len(th.episodes(flags, ecart_max=7)) == 1
    assert th.intensity_from_rank(0.90) == pytest.approx(0.3) and th.intensity_from_rank(0.999) == pytest.approx(1.0)


def test_weather_calibration_is_site_specific():
    hist = add_indicators(synthetic_history())
    cal = calibrate_site("x", hist, ["pluie_3j", "rafales", "gel", "crue"])
    assert set(cal.indicators) == {"pluie_3j", "rafales", "gel"}, "pas de débit : pas de seuil de crue"
    calib = hist[hist["date"] <= "2020-12-31"]
    assert cal.indicators["rafales"].seuil == pytest.approx(calib["wind_gusts_10m_max"].quantile(0.99), rel=1e-3)
    ev = evaluate_site(hist, cal)
    rate = ev.loc[ev["date"] <= "2020-12-31", "alerte_rafales"].mean()
    assert 0.005 < rate < 0.015, "1 % des jours de calibration dépassent le centile 99"
    assert ev.loc[ev["date"] <= "2020-12-31", "score_meteo"].median() == pytest.approx(0.5, abs=0.05)


@pytest.mark.skipif(not (NOTEBOOKS / "meteo" / "sorties").exists(), reason="sorties du notebook météo absentes")
def test_weather_module_reproduces_notebook_thresholds():
    sorties = NOTEBOOKS / "meteo" / "sorties"
    brut = pd.read_csv(sorties / "meteo_brut.csv", parse_dates=["date"])
    ref = pd.read_csv(sorties / "meteo_seuils_par_site.csv")
    sites = pd.read_csv(sorties / "meteo_sites.csv")
    for s in sites.itertuples():
        cal = calibrate_site(s.site, add_indicators(brut[brut["site"] == s.site]), [i.strip() for i in s.indicateurs.split(",")])
        for ind, c in cal.indicators.items():
            expected = ref[(ref["site"] == s.site) & (ref["indicateur"] == ind)]["seuil"].iloc[0]
            assert c.seuil == pytest.approx(expected, abs=0.01), (s.site, ind)


# ----------------------------------------------------------------------------- moteur
def test_intensity_uses_rank_when_calibrated(engine):
    ev = weather_event("w", "2026-11-16", "port_rotterdam", "Port of Rotterdam", gust=60, rain=0)
    assert event_intensity(ev) == pytest.approx(0.3), "seuils fixes : rafales faibles"
    calibrated = ev.model_copy(update={"weather": ev.weather.model_copy(update={"rank": 0.999, "indicator": "rafales"})})
    assert event_intensity(calibrated) == pytest.approx(1.0)


def test_multi_node_stress_test_never_touches_real_state(engine):
    engine.reset()
    single = engine.simulate_disruption("port_rotterdam", 0.6)
    multi = engine.simulate_disruption("port_rotterdam", 0.6, {"port_hamburg": 0.6})
    assert multi.simulated_index > single.simulated_index
    assert engine.current.index == 0.0 and engine.current.direct == {}


def test_real_topology_bindings():
    eng = OntologyEngine.from_yaml(ROOT / "data" / "topologies" / "semis_reels.yaml")
    cfg = eng.weather_site_config()
    assert cfg["hub_kaub"]["site"] == "kaub_rhin" and cfg["hub_kaub"]["indicators"] == ["basses_eaux", "crue"]
    assert {s["proxy"] for s in eng.supplier_bindings} >= {"nexperia", "wolfspeed", "nyrstar"}
    bindings = {b["signal"]: b for b in SupplyChainService.signal_bindings(eng)}
    assert bindings["gaz_europe"]["exact"] == ["rm_zinc_nyrstar"]
    assert set(bindings["brent"]["exposed"]) == {"port_rotterdam_r", "port_hamburg_r"}


# ----------------------------------------------------------------------------- agents
def test_weather_agent_uses_site_calibration_in_live(service, monkeypatch):
    import src.agents.weather_agent as wa
    agent = service.agents["weather"]
    cal = calibrate_site("rotterdam", add_indicators(synthetic_history()), ["rafales", "neige"])
    monkeypatch.setattr(agent, "_calibrations_loader", lambda: {"port_rotterdam": cal})
    hubs = list(agent.hubs.values())
    today = date.today()
    days = [(today + timedelta(days=k)).isoformat() for k in range(-2, 4)]
    calm = {"time": days, "wind_speed_10m_max": [20] * 6, "wind_gusts_10m_max": [40] * 6, "precipitation_sum": [0] * 6,
            "weather_code": [3] * 6, "temperature_2m_max": [12] * 6, "temperature_2m_min": [5] * 6, "snowfall_sum": [0] * 6}
    storm = dict(calm, wind_gusts_10m_max=[40, 40, 40, 40, cal.indicators["rafales"].seuil + 15, 40])

    class Resp:
        def json(self):
            return [{"daily": storm if h.id == "port_rotterdam" else calm} for h in hubs]
    monkeypatch.setattr(wa, "http_get", lambda *a, **k: Resp())
    res = run(agent.run(mode="live"))
    assert res.status == "success" and res.sources["open_meteo"]["calibres"] == 1
    [ev] = res.events
    w = ev.weather
    assert ev.meta.extractor == "seuils_calibres" and w.indicator == "rafales" and w.forecast and w.rank > 0.99
    assert w.threshold == pytest.approx(cal.indicators["rafales"].seuil, abs=1e-3) and "seuil du site" in ev.event.label


def test_finance_agent_replays_calibrated_signals(service):
    agent = service.agents["finance"]
    days = pd.bdate_range("2015-01-01", "2026-09-30")
    rng = np.random.default_rng(1)
    values = 60 * np.exp(np.cumsum(rng.normal(0, 0.01, len(days))))
    values[-15:] *= np.linspace(1.0, 1.6, 15)                # flambée finale
    scenario = {"finance": {}, "finance_signals": {"cuivre": [{"date": str(d.date()), "valeur": float(v)} for d, v in zip(days, values)]}}
    res = run(agent.run(mode="replay", scenario=scenario, as_of="2026-09-30"))
    [ev] = [e for e in res.events if e.finance.kind == "signal"]
    assert ev.finance.instrument == "cuivre" and ev.finance.rank >= 0.99 and ev.event.type == "tension_marche"
    assert {e.id for e in ev.entities} == {"NODE:rm_copper"} and ev.date < "2026-09-30", "daté au début de l'épisode"


def test_supplier_sheet_events(service):
    agent = service.agents["finance"]
    fiche = {"cle": "nexperia", "fournisseur": "Nexperia", "pays": "NL", "produit": "Puces", "node": "sup_chip_nl", "date": "2024-12-10",
             "bourse": None, "sanctions": [{"entite": "Wingtech", "role": "maison mère ultime", "liste": "US : Entity List",
                                            "nom_sur_liste": "Wingtech", "date_inscription": "2024-12-05", "source_id": "csl:1"}],
             "procedures_collectives": []}
    evs = run(agent.extract_events({"_suppliers": [fiche]}))
    assert [e.event.type for e in evs] == ["sanction"] and evs[0].date == "2024-12-05"
    assert event_intensity(evs[0]) == 1.0


# ----------------------------------------------------------------------------- base unifiée et API
def test_pipeline_runs_are_recorded(service):
    run(service.run_pipeline(PipelineRunRequest(mode="replay", scenario=SCENARIO, day=3)))
    run(service.run_pipeline(PipelineRunRequest(mode="replay", scenario=SCENARIO, day=7)))
    runs = db.query("SELECT * FROM runs ORDER BY started_at")
    assert len(runs) == 2 and list(runs["as_of"].astype(str)) == ["2026-09-16", "2026-09-20"]
    hist = db.query("SELECT * FROM node_risk_history WHERE run_id=?", [runs["run_id"].iloc[-1]])
    assert len(hist) == len(service.engine.nodes)
    ev = db.query("SELECT * FROM events")
    assert set(ev["agent"]) == {"media", "weather", "finance"} and ev["event_id"].is_unique
    links = db.query("SELECT DISTINCT kind FROM entity_bindings")
    assert set(links["kind"]) >= {"weather_site", "market_signal", "supplier", "instrument"}


def test_data_endpoints_without_data_never_fail():
    c = TestClient(create_app())
    assert c.get("/weather/overview").json()["ready"] is False
    assert c.get("/finance/overview").json()["ready"] is False
    assert c.get("/history/runs").json() == []
    assert c.post("/jobs/calibrate-meteo").status_code == 400


def test_stress_tests_and_multi_node_simulation():
    c = TestClient(create_app())
    tests = c.get("/graph/stress-tests").json()
    families = {t["family"] for t in tests}
    assert {"climat", "marche", "reglementaire", "financier"} <= families
    brent = next(t for t in tests if t["id"] == "fin:brent")
    first, *_ = brent["shocks"]
    res = c.post("/graph/simulate", json={"node_id": first, "severity": brent["shocks"][first], "extra": brent["shocks"]})
    assert res.status_code == 200 and res.json()["simulated_index"] > res.json()["baseline_index"]


@pytest.mark.skipif(not (NOTEBOOKS / "finance" / "sorties").exists(), reason="sorties des notebooks absentes")
def test_import_notebooks_then_pages():
    from src.jobs.__main__ import main
    assert main(["import-notebooks", "--dir", str(NOTEBOOKS)]) == 0
    c = TestClient(create_app())
    wx = c.get("/weather/overview").json()
    assert wx["ready"] and wx["kpis"]["sites"] == 10 and wx["kpis"]["hubs_calibrated"] == 4
    assert {n["node_id"] for s in wx["sites"] for n in s["nodes"]} == {"port_rotterdam", "port_hamburg", "port_kaohsiung", "port_shanghai"}
    series = c.get("/weather/sites/kaub_rhin/series", params={"indicator": "basses_eaux", "days": 90}).json()
    assert series["threshold"] == pytest.approx(547.7, abs=0.1) and series["series"][0]["p50"] is not None
    fin = c.get("/finance/overview").json()
    seuils = {s["signal"]: s["seuil"] for s in fin["signals"]}
    assert seuils["gaz_europe"] == pytest.approx(8.87, abs=0.01) and seuils["brent"] == pytest.approx(25.58, abs=0.01)
    nexperia = c.get("/finance/suppliers/nexperia").json()
    assert nexperia["node"] == "sup_chip_nl" and nexperia["proprietaires"][0]["nom"].startswith("Wingtech")
