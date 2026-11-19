"""Agent médias (Bloc 2) : logique du notebook v2, asynchrone.

Les fonctions `collect_live`, `collect_replay`, `extract_events` restent indépendantes : ce sont elles que
l'orchestrateur appelle. La collecte bloquante (requests, gdeltdoc) tourne dans des fils.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.agents.base import BaseAgent
from src.agents.media_nlp import MediaNLP
from src.agents.media_sources import (Article, articles_as_of, finalize_articles, ingest_gdelt_with_fallback,
                                      ingest_gkg_replay, ingest_rss, parse_dt)
from src.config import settings
from src.schemas.events import NormalizedEvent


class MediaAgent(BaseAgent):
    name = "media"

    def __init__(self, companies: list[dict], places: list[dict], soft_terms: Optional[list[dict]] = None,
                 node_names: Optional[dict[str, str]] = None):
        self.nlp = MediaNLP(companies, places, soft_terms, node_names)

    async def collect_live(self, report: Optional[dict] = None, days: Optional[int] = None, use_gdelt: bool = True,
                           use_rss: bool = True, countries=None, **kwargs) -> list[Article]:
        """Articles des `days` derniers jours (GDELT DOC + RSS). Les deux sources sont indépendantes.

        Si GDELT refuse la requête pour limite de débit, Google News RSS prend le relais sur les mêmes mots-clés."""
        report = {} if report is None else report
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days or settings.lookback_days)
        jobs = []
        if use_gdelt:
            jobs.append(asyncio.to_thread(ingest_gdelt_with_fallback, start, end, countries=countries, report=report))
        if use_rss:
            jobs.append(asyncio.to_thread(ingest_rss, since=start, report=report))
        parts = await asyncio.gather(*jobs)
        return finalize_articles([a for part in parts for a in part])

    async def collect_replay(self, scenario: dict, as_of: Optional[str] = None, report: Optional[dict] = None) -> list[Article]:
        """Articles d'un scénario, vus à la date `as_of`."""
        report = {} if report is None else report
        arts = finalize_articles([
            Article(source_id=a["source_id"], source_type="replay", title=a["title"], text=a.get("text", ""),
                    url=a.get("url") or "https://replay.local/" + a["source_id"].replace(":", "/"),
                    published_at=parse_dt(a.get("published_at")), domain="replay.local",
                    language=a.get("language"), source_country=a.get("source_country"))
            for a in scenario.get("media", [])])
        if as_of:
            arts = articles_as_of(arts, as_of)
        report["scenario"] = {"status": "ok", "articles": len(arts)}
        return arts

    async def collect_gkg_replay(self, start: str, end: str, patterns: list[str], as_of: Optional[str] = None,
                                 report: Optional[dict] = None, **kwargs) -> list[Article]:
        """Articles GKG 2.1 d'une période passée réelle (backtesting), vus à la date `as_of`."""
        arts = await asyncio.to_thread(ingest_gkg_replay, start, end, patterns, report=report, **kwargs)
        return articles_as_of(arts, as_of) if as_of else arts

    async def extract_events(self, raw: list[Article], use_llm: Optional[bool] = None, broad_linking: bool = False,
                             **kwargs) -> list[NormalizedEvent]:
        return await asyncio.to_thread(self.nlp.extract_events, raw, use_llm, broad_linking)

    def _extraction_log(self) -> list[dict]:
        return list(self.nlp.journal)
