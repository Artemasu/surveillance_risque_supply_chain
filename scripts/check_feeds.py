"""Teste depuis votre poste les sources médias du mode live : flux RSS, GDELT et Google News.

    python scripts/check_feeds.py            # flux RSS seulement (rapide)
    python scripts/check_feeds.py --all      # ajoute GDELT et le repli Google News

À lancer avant une démonstration : un flux qui renvoie 403 ou 404 se remplace dans RSS_FEEDS
(src/agents/media_sources.py). Une valeur peut être une liste d'adresses de rechange.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents import media_sources as ms  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Vérifie les sources médias du mode live.")
    ap.add_argument("--all", action="store_true", help="teste aussi GDELT et Google News")
    args = ap.parse_args(argv)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=7)
    failures = 0
    print(f"{len(ms.RSS_FEEDS)} flux RSS")
    for name, urls in ms.RSS_FEEDS.items():
        report: dict = {}
        arts = ms.ingest_rss({name: urls}, since=start, keep_filter=False, report=report)
        ok = report["rss"]["status"] == "ok"
        failures += not ok
        detail = f"{len(arts)} articles sur 7 jours" if ok else report["rss"]["echecs"].get(name, "échec")
        print(f"  {'OK    ' if ok else 'ÉCHEC '} {name:24s} {detail}")
    if args.all:
        for label, fn in (("GDELT", ms.ingest_gdelt_live), ("Google News", ms.ingest_google_news)):
            report = {}
            arts = fn(start, end, report=report, use_cache=False)
            state = next(iter(report.values()))
            ok = state["status"] == "ok"
            failures += not ok
            print(f"  {'OK    ' if ok else 'ÉCHEC '} {label:24s} {len(arts)} articles" + ("" if ok else f" · {state.get('detail', '')}"))
    print("Tout répond." if not failures else f"{failures} source(s) en échec.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
