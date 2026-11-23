"""Tâches de la base unifiée, en ligne de commande.

    python -m src.jobs import-notebooks            sorties des notebooks Météo et Finance -> base (sans réseau)
    python -m src.jobs calibrate-meteo [--topology topologies/semis_reels.yaml] [--force]
                                                   historique ERA5 et seuils des hubs d'une topologie (réseau)
    python -m src.jobs forecast-meteo              prévisions 16 jours des sites calibrés (réseau, ~1 appel par site)
    python -m src.jobs ingest-finance [--sans-fournisseurs]
                                                   signaux de marché, fiches fournisseurs, règles (réseau)
    python -m src.jobs status                      contenu de la base
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from src.config import ROOT, settings


def _engine(topology: str | None):
    from src.graph.ontology_engine import OntologyEngine
    path = settings.data_dir / topology if topology else settings.topology_path
    return OntologyEngine.from_yaml(path), (topology or "topology.yaml")


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(prog="python -m src.jobs", description="Tâches de la base unifiée A.E.G.I.S.")
    sub = p.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import-notebooks", help="importer les sorties des notebooks Météo et Finance")
    imp.add_argument("--dir", default=str(ROOT / "surveillance_risque_supply_chain-main"))
    cal = sub.add_parser("calibrate-meteo", help="calibrer les hubs météo d'une topologie")
    cal.add_argument("--topology", help="relative à data/ (défaut : topologie par défaut)")
    cal.add_argument("--debut", default="2010-01-01")
    cal.add_argument("--force", action="store_true", help="recalibrer aussi les sites déjà calibrés")
    cal.add_argument("--node", action="append", help="limiter à ces nœuds")
    sub.add_parser("forecast-meteo", help="prévisions à 16 jours des sites calibrés")
    fin = sub.add_parser("ingest-finance", help="collecter les signaux finance")
    fin.add_argument("--sans-fournisseurs", action="store_true")
    fin.add_argument("--sans-regles", action="store_true")
    sub.add_parser("status", help="contenu de la base")
    a = p.parse_args(argv)

    from src.storage import db
    db.ensure_schema()
    if a.cmd == "import-notebooks":
        from src.jobs import finance, meteo
        folder = Path(a.dir)
        if not folder.exists():
            print(f"dossier introuvable : {folder}")
            return 1
        res = {"meteo": meteo.import_notebook(folder), "finance": finance.import_notebook(folder)}
    elif a.cmd == "calibrate-meteo":
        from src.jobs import meteo
        engine, ref = _engine(a.topology)
        res = meteo.calibrate_topology(engine, ref, a.debut, a.force, a.node)
    elif a.cmd == "forecast-meteo":
        from src.jobs import meteo
        res = meteo.forecast_sites()
    elif a.cmd == "ingest-finance":
        from src.jobs import finance
        res = finance.ingest(suppliers=not a.sans_fournisseurs, rules=not a.sans_regles)
    else:
        tables = ["wx_sites", "thresholds", "indicators", "wx_forecast", "validation", "fin_raw", "fin_suppliers",
                  "fin_rules", "events", "runs", "node_risk_history"]
        res = {t: int(db.query(f"SELECT COUNT(*) AS n FROM {t}")["n"].iloc[0]) for t in tables}
        res["fichier"] = str(settings.db_path)
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
