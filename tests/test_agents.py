"""Agents médias, météo et finance : replay, contrat de réponse, règle zéro démo."""
import asyncio
import io
import json
import zipfile

import pytest

from src.agents import media_sources
from src.agents.base import BaseAgent
from src.agents.finance_agent import five_day_changes, is_anomaly
from src.agents.media_nlp import keyword_classify
from src.agents.media_sources import GKG_COLS, ingest_gkg_replay, ingest_rss
from src.utils import llm
from tests.conftest import SCENARIO


@pytest.fixture
def scenario(service):
    return service.load_scenario(SCENARIO)


def run(coro):
    return asyncio.run(coro)


# ----------------------------------------------------------------------------- médias
def test_media_replay_events_respect_contract(service, scenario):
    res = run(service.agents["media"].run(mode="replay", scenario=scenario, as_of="2026-09-20"))
    assert res.status == "success" and not res.degraded and res.count == len(res.events) >= 10
    known = {a["source_id"] for a in scenario["media"]}
    for ev in res.events:
        assert ev.meta.agent == "media" and ev.event.type != "aucun"
        assert ev.media and all(m.source_id in known for m in ev.media), "aucun fait sans source"
        assert ev.date == min(m.date for m in ev.media)[:10], "date = plus ancien article, calculée par le code"
        assert ev.weather is None and ev.finance is None and {"weather", "finance"} <= set(ev.donnees_manquantes)
        assert all(e.id is None or e.id.startswith("SUP:") for e in ev.entities), "aucun LEI inventé"
    types = {ev.event.type for ev in res.events}
    assert {"catastrophe", "greve", "penurie", "logistique"} <= types


def test_media_deduplicates_and_filters(service, scenario):
    res = run(service.agents["media"].run(mode="replay", scenario=scenario, as_of="2026-09-20"))
    sizes = sorted(len(ev.media) for ev in res.events)
    assert sizes[-1] == 2, "les deux dépêches sur l'usine de Tainan forment un seul événement"
    cited = {m.source_id for ev in res.events for m in ev.media}
    assert "replay:crisis_asia:008" not in cited, "l'article sans rapport (salon automobile) est classé « aucun »"
    assert len(res.extraction) == len(res.events) + 1


def test_media_as_of_hides_the_future(service, scenario):
    res = run(service.agents["media"].run(mode="replay", scenario=scenario, as_of="2026-09-15"))
    assert res.events and all(ev.date <= "2026-09-15" for ev in res.events)
    assert all(m.date[:10] <= "2026-09-15" for ev in res.events for m in ev.media)


def test_media_locations_and_entities_come_from_referentials(service, scenario):
    res = run(service.agents["media"].run(mode="replay", scenario=scenario, as_of="2026-09-20"))
    by_source = {m.source_id: ev for ev in res.events for m in ev.media}
    port = by_source["replay:crisis_asia:002"]
    assert port.location.name == "Port of Kaohsiung" and port.location.lat == pytest.approx(22.61)
    fab = by_source["replay:crisis_asia:005"]
    assert [e.id for e in fab.entities] == ["SUP:sup_chip_tw"] and fab.entities[0].role == "touché"
    assert "entities.lei" in fab.donnees_manquantes


def test_keyword_baseline():
    assert keyword_classify("Dockworkers begin a strike at the port")[0] == "greve"
    assert keyword_classify("Une cyberattaque paralyse l'usine")[0] == "cyberattaque"
    assert keyword_classify("The museum opens a new exhibition") == ("aucun", 0, [])


def test_live_failure_is_an_error_never_demo_data(service, monkeypatch):
    """Réseau coupé : status=error / network_failure, et aucun événement de scénario."""
    monkeypatch.setattr(media_sources, "http_get", lambda *a, **k: None)
    monkeypatch.setattr(media_sources, "ingest_gdelt_live",
                        lambda *a, report=None, **k: report.update(gdelt={"status": "failed", "detail": "coupé"}) or [])
    res = run(service.agents["media"].run(mode="live"))
    assert res.status == "error" and res.error_type == "network_failure"
    assert res.events == [] and res.count == 0
    assert res.sources["rss"]["status"] == "failed" and res.sources["gdelt"]["status"] == "failed"


def test_rss_distinguishes_site_refusal_from_network_outage(monkeypatch):
    def refused(url, info=None, **k):
        info.update(status=403, error=None)
    report = {}
    monkeypatch.setattr(media_sources, "http_get", refused)
    assert ingest_rss({f"flux{i}": f"https://example.org/{i}" for i in range(5)}, report=report) == []
    assert len(report["rss"]["echecs"]) == 5, "un refus 403 n'arrête pas la collecte"

    calls = []
    def outage(url, info=None, **k):
        calls.append(url)
        info.update(status=None, error="ConnectionError")
    report = {}
    monkeypatch.setattr(media_sources, "http_get", outage)
    ingest_rss({f"flux{i}": f"https://example.org/{i}" for i in range(5)}, report=report)
    assert len(calls) == 3, "trois pannes réseau de suite : on arrête d'attendre"


def test_rss_parsing_and_supply_filter(monkeypatch):
    feed = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
      <item><title>Dockworkers strike closes the port</title><link>https://example.org/a?utm=1</link>
            <pubDate>Mon, 14 Sep 2026 08:00:00 GMT</pubDate><description>Cargo &amp; ships wait.</description></item>
      <item><title>Recipe of the week</title><link>https://example.org/b</link><description>Soup.</description></item>
    </channel></rss>"""
    class Resp:
        content = feed
    monkeypatch.setattr(media_sources, "http_get", lambda url, info=None, **k: Resp())
    report = {}
    arts = ingest_rss({"demo": "https://example.org/rss"}, report=report)
    assert [a.title for a in arts] == ["Dockworkers strike closes the port"]
    assert arts[0].source_id.startswith("rss:demo:") and arts[0].published_at.year == 2026
    assert report["rss"]["status"] == "ok"


def test_gkg_replay_from_local_files(tmp_path):
    def row(record, url, title, orgs):
        values = dict.fromkeys(GKG_COLS, "")
        values.update(GKGRECORDID=record, DATE="20251004081500", SourceCommonName="example.org",
                      DocumentIdentifier=url, V2Organizations=orgs, Extras=f"<PAGE_TITLE>{title}</PAGE_TITLE>")
        return "\t".join(values[c] for c in GKG_COLS)
    lines = [row("20251004081500-1", "https://example.org/n", "China bans exports of Nexperia chips", "Nexperia,10"),
             row("20251004081500-2", "https://example.org/f", "Football results", "FC Somewhere,5"), "ligne cassée"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("20251004081500.gkg.csv", "\n".join(lines))
    (tmp_path / "20251004081500.gkg.csv.zip").write_bytes(buf.getvalue())
    (tmp_path / "20251004083000.gkg.csv.zip").write_bytes(b"pas un zip")
    report = {}
    arts = ingest_gkg_replay("2025-10-04", "2025-10-04", ["nexperia"], local_dir=tmp_path, report=report)
    assert [a.source_id for a in arts] == ["gkg:20251004081500-1"]
    assert arts[0].title == "China bans exports of Nexperia chips"
    assert report["gkg"]["status"] == "partial" and report["gkg"]["illisibles"] == 1


def _fake_llm(monkeypatch, answer):
    import src.agents.media_nlp as nlp
    monkeypatch.setattr(nlp, "llm_available", lambda: True)
    monkeypatch.setattr(nlp, "call_llm", lambda system, user, timeout=None: answer(user) if callable(answer) else answer)


def test_llm_output_is_checked_and_grounded(service, scenario, monkeypatch):
    """Le LLM hallucine une entreprise, des coordonnées et une date : le code les écarte ou les recalcule."""
    def answer(user):
        cid = user.split("Identifiant de l'événement : ")[1].split("\n")[0]
        return json.dumps({"event": {"id": cid, "type": "catastrophe", "label": "Un typhon inonde l'usine de Tainan"},
                           "date": "1999-01-01", "location": {"name": "Tainan", "lat": 1.0, "lon": 2.0},
                           "entities": [{"id": "LEI:FAUX", "name": "Formoz Power Semi", "role": "touché"},
                                        {"id": None, "name": "Entreprise Inventée SA", "role": "touché"}],
                           "media": [{"titre": "faux", "date": "x", "source_id": "invente:1"}]})
    _fake_llm(monkeypatch, answer)
    agent = service.agents["media"]
    arts = [a for a in run(agent.collect_replay(scenario)) if a.source_id.endswith(("005", "006"))]
    events = run(agent.extract_events(arts, use_llm=True))
    assert len(events) == 1
    ev = events[0]
    assert ev.meta.extractor == "llm" and ev.event.label == "Un typhon inonde l'usine de Tainan"
    assert ev.date == "2026-09-16", "la date vient du plus ancien article"
    assert ev.location.lat == pytest.approx(22.99), "les coordonnées viennent du référentiel"
    assert [e.id for e in ev.entities] == ["SUP:sup_chip_tw"], "identifiant du référentiel, entité inventée écartée"
    assert {m.source_id for m in ev.media} == {"replay:crisis_asia:005", "replay:crisis_asia:006"}
    assert "écartée" in agent.nlp.journal[0]["detail"]


@pytest.mark.parametrize("bad", ["pas du json", '{"event": {"type": "greve"}}',
                                 '{"event": {"id": "x", "type": "invasion", "label": "x"}, "date": null, "location": {}, "entities": [], "media": []}'])
def test_llm_garbage_falls_back_to_baseline(service, scenario, monkeypatch, bad):
    _fake_llm(monkeypatch, bad)
    agent = service.agents["media"]
    arts = [a for a in run(agent.collect_replay(scenario)) if a.source_id.endswith("009")]
    events = run(agent.extract_events(arts, use_llm=True))
    assert len(events) == 1 and events[0].meta.extractor == "baseline" and events[0].event.type == "greve"
    assert agent.nlp.journal[0]["detail"].startswith("repli sur la baseline")


def test_llm_unreachable_falls_back_without_crash(service, scenario, monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_base_url", "http://127.0.0.1:9")       # rien n'écoute sur ce port
    res = run(service.agents["media"].run(mode="replay", scenario=scenario, as_of="2026-09-16", use_llm=True))
    assert res.status == "success" and res.events
    assert all(row["extracteur"] == "baseline" and "injoignable" in row["detail"] for row in res.extraction)


# ----------------------------------------------------------------------------- météo
def test_weather_replay_detects_typhoon_as_early_signal(service, scenario):
    agent = service.agents["weather"]
    day1 = run(agent.run(mode="replay", scenario=scenario, as_of="2026-09-14"))
    assert [e.weather.hub for e in day1.events] == ["port_kaohsiung"]
    forecast = day1.events[0]
    assert forecast.weather.forecast and forecast.weather.date == "2026-09-16" and forecast.date == "2026-09-14"
    assert forecast.meta.confidence == 0.7

    day3 = run(agent.run(mode="replay", scenario=scenario, as_of="2026-09-16"))
    by_hub = {e.weather.hub: e for e in day3.events}
    assert set(by_hub) == {"port_kaohsiung", "sup_chip_tw", "port_keelung"}
    peak = by_hub["port_kaohsiung"]
    assert not peak.weather.forecast and peak.weather.gust_max_kmh == 185
    assert peak.date == "2026-09-14", "la date reste celle du premier signal"
    assert peak.entities[0].id == "NODE:port_kaohsiung" and peak.weather.source_id.startswith("replay:meteo:")


def test_weather_live_parses_open_meteo(service, monkeypatch):
    import src.agents.weather_agent as wa
    agent = service.agents["weather"]
    hubs = list(agent.hubs.values())
    calm = {"time": ["2020-01-01", "2020-01-02"], "wind_speed_10m_max": [20, 25], "wind_gusts_10m_max": [35, 40],
            "precipitation_sum": [0, 1], "weather_code": [3, 3]}
    storm = dict(calm, wind_gusts_10m_max=[35, 140], precipitation_sum=[0, 90])
    class Resp:
        def json(self):
            return [{"daily": storm if h.id == "port_rotterdam" else calm} for h in hubs]
    monkeypatch.setattr(wa, "http_get", lambda *a, **k: Resp())
    res = run(agent.run(mode="live"))
    assert res.status == "success" and [e.weather.hub for e in res.events] == ["port_rotterdam"]
    assert res.events[0].weather.gust_max_kmh == 140 and res.events[0].weather.provider == "open-meteo"

    monkeypatch.setattr(wa, "http_get", lambda *a, **k: None)
    down = run(agent.run(mode="live"))
    assert down.status == "error" and down.error_type == "network_failure" and down.events == []


# ----------------------------------------------------------------------------- finance
def test_finance_replay_flags_freight_and_chips_only(service, scenario):
    agent = service.agents["finance"]
    assert run(agent.run(mode="replay", scenario=scenario, as_of="2026-09-14")).events == [], "pas de fausse alerte avant la crise"
    res = run(agent.run(mode="replay", scenario=scenario, as_of="2026-09-20"))
    by_id = {e.finance.instrument: e for e in res.events}
    assert set(by_id) == {"FRET_ASIE_EUROPE", "PUCES_PUISSANCE"}, "lithium, cuivre et terres rares restent calmes"
    freight = by_id["FRET_ASIE_EUROPE"]
    assert freight.finance.change_5d_pct > 25 and freight.finance.zscore > 3 and freight.event.type == "tension_marche"
    assert {e.id for e in freight.entities} == {"NODE:port_kaohsiung", "NODE:port_shanghai", "NODE:port_singapore"}
    assert freight.date < by_id["PUCES_PUISSANCE"].date, "le fret décroche avant le prix des puces"


def test_finance_maths():
    closes = [100, 100, 100, 100, 100, 110]
    assert five_day_changes(closes)[-1] == pytest.approx(10.0) and five_day_changes(closes)[0] is None
    assert is_anomaly(9.0, None) and is_anomaly(-9.0, None)
    assert is_anomaly(4.0, 3.0) and not is_anomaly(2.0, 5.0) and not is_anomaly(4.0, 1.0) and not is_anomaly(None, 9.0)


def test_finance_live_without_network(service, monkeypatch):
    agent = service.agents["finance"]
    def boom(symbol):
        raise ConnectionError("réseau coupé")
    monkeypatch.setattr(agent, "_download", boom)
    res = run(agent.run(mode="live"))
    assert res.status == "error" and res.error_type in {"network_failure", "source_unavailable"} and res.events == []


# ----------------------------------------------------------------------------- contrat commun
def test_base_agent_contract(service):
    assert all(isinstance(a, BaseAgent) for a in service.agents.values())
    with pytest.raises(TypeError):
        BaseAgent()
    bad_mode = run(service.agents["weather"].run(mode="demo"))
    assert bad_mode.status == "error" and bad_mode.error_type == "invalid_request"
    no_scenario = run(service.agents["finance"].run(mode="replay"))
    assert no_scenario.error_type == "invalid_request"


def test_agent_never_raises(service, scenario, monkeypatch):
    agent = service.agents["weather"]
    async def broken(raw, **k):
        raise RuntimeError("bug")
    monkeypatch.setattr(agent, "extract_events", broken)
    res = run(agent.run(mode="replay", scenario=scenario))
    assert res.status == "error" and res.error_type == "internal_error" and "bug" in res.error_message
