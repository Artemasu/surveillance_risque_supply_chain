"""Génère une topologie de départ et un scénario de replay vide pour un secteur et une entreprise.

    python scripts/generate_sector_config.py --list
    python scripts/generate_sector_config.py --sector pharma --company "Helvia Pharma"
    python scripts/generate_sector_config.py --sector generique --company "Ma PME" --name ma_pme --days 5
    python scripts/generate_sector_config.py --check data/topologies/pharma_helvia_pharma.yaml

Le script écrit :
  data/topologies/<nom>.yaml              la chaîne d'approvisionnement, à corriger avec vos vrais fournisseurs ;
  data/replay_scenarios/<nom>_modele.json un scénario vide mais valide (météo calme, cours plats, aucun article),
                                          à compléter avec les événements que vous voulez rejouer.
Les fournisseurs des gabarits sont INVENTÉS : ce sont des exemples de structure, pas des données de marché.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.scenario_tools import build_finance, build_weather, day_map  # noqa: E402
from src.graph.ontology_engine import OntologyEngine  # noqa: E402


def N(id, name, type, tier, crit, country=None, place=None, lat=None, lon=None, stock=0, aliases=(), company=False,
      keywords=()):
    node = {"id": id, "name": name, "type": type, "tier": tier, "criticality": crit}
    if place:
        node.update(country=country, place=place, lat=lat, lon=lon, weather_watch=type != "matiere_premiere")
    if stock:
        node["stock_days"] = stock
    if company:
        node["company"] = True
    node["aliases"] = list(aliases)
    if keywords:
        node["keywords"] = list(keywords)                # mots-clés sectoriels pour le rattachement élargi des articles
    return node


def E(source, target, input, dependency, lead=0, backup=False, capacity=0.0):
    edge = {"source": source, "target": target, "input": input, "dependency": dependency, "lead_time_days": lead}
    if backup:
        edge["backup"] = True
    if capacity:
        edge["capacity"] = capacity
    return edge


# {company} : nom complet de l'entreprise. {short} : son premier mot (« Helvia » pour « Helvia Pharma »).
PRESETS = {
    "pharma": {
        "label": "Pharmacie : principes actifs (API) d'Inde et de Chine, remplissage et conditionnement en Europe",
        "nodes": [
            N("rm_ksm", "Intermédiaires chimiques (KSM)", "matiere_premiere", 4, 0.7, "China", "Taizhou", 28.66, 121.42, aliases=["key starting materials", "antibiotic intermediates"]),
            N("rm_solvents", "Solvants", "matiere_premiere", 4, 0.4, "Germany", "Ludwigshafen", 49.48, 8.44),
            N("rm_borosilicate", "Verre borosilicaté", "matiere_premiere", 4, 0.5, "Germany", "Mainz", 50.00, 8.27, aliases=["borosilicate glass"]),
            N("sup_api_in", "Deccan Actives", "fournisseur", 2, 0.9, "India", "Hyderabad", 17.39, 78.49, 20, ["Deccan Actives Ltd"], True, keywords=["active pharmaceutical ingredient", "antibiotic", "antibiotique", "principe actif", "drug shortage", "pénurie de médicaments"]),
            N("sup_api_cn", "Jiangnan BioChem", "fournisseur", 2, 0.6, "China", "Shaoxing", 30.00, 120.58, 20, ["Jiangnan BioChem Co"], True, keywords=["active pharmaceutical ingredient", "antibiotic", "antibiotique", "principe actif", "drug shortage", "pénurie de médicaments"]),
            N("sup_api_it", "Lombarda Chimica", "fournisseur", 2, 0.7, "Italy", "Bergamo", 45.70, 9.67, 25, ["Lombarda Chimica SpA"], True, keywords=["active pharmaceutical ingredient", "principe actif", "antidiabétique"]),
            N("sup_vials_de", "Rheinglas Pharma", "fournisseur", 2, 0.7, "Germany", "Mainz", 50.00, 8.27, 30, ["Rheinglas"], True, keywords=["glass vials", "flacons en verre"]),
            N("sup_excip_fr", "Excipia", "fournisseur", 2, 0.4, "France", "Lyon", 45.76, 4.84, 30, ["Excipia SAS"], True),
            N("sup_pack_pl", "Wisla Pack", "fournisseur", 2, 0.4, "Poland", "Lodz", 51.76, 19.46, 30, ["Wisla Pack Sp"], True),
            N("port_nhava_sheva", "Port of Nhava Sheva", "port", 2, 0.8, "India", "Nhava Sheva", 18.95, 72.95, aliases=["Nhava Sheva port", "JNPT", "Jawaharlal Nehru Port", "port de Nhava Sheva"]),
            N("port_shanghai", "Port of Shanghai", "port", 2, 0.6, "China", "Shanghai", 31.23, 121.49, aliases=["Shanghai port", "port de Shanghai", "Shanghai"]),
            N("port_antwerp", "Port of Antwerp", "port", 2, 0.9, "Belgium", "Antwerp", 51.27, 4.34, aliases=["Antwerp port", "port d'Anvers", "Antwerp-Bruges", "Antwerp", "Anvers"]),
            N("port_le_havre", "Port of Le Havre", "port", 2, 0.6, "France", "Le Havre", 49.48, 0.13, aliases=["port du Havre", "Le Havre"]),
            N("hub_air_cdg", "Fret aérien Paris-CDG", "hub", 2, 0.3, "France", "Roissy", 49.01, 2.55, aliases=["Paris-CDG cargo", "fret aérien de Roissy"]),
            N("plant_ff_fr", "{short} Tours (injectables)", "usine", 1, 0.9, "France", "Tours", 47.39, 0.69, 30, ["{short} Tours", "usine de Tours", "Tours plant"], True),
            N("plant_oral_ie", "{short} Cork (formes orales)", "usine", 1, 0.8, "Ireland", "Cork", 51.90, -8.47, 30, ["{short} Cork", "usine de Cork", "Cork plant"], True),
            N("prod_antibio_inj", "Antibiotique injectable Cefalia", "produit_fini", 0, 1.0, aliases=["Cefalia"]),
            N("prod_antibio_oral", "Antibiotique oral Amoxiral", "produit_fini", 0, 0.8, aliases=["Amoxiral"]),
            N("prod_antidiab", "Antidiabétique oral Glumera", "produit_fini", 0, 0.8, aliases=["Glumera"]),
        ],
        "edges": [
            E("rm_ksm", "sup_api_in", "intermediaires", 1.0, 35), E("rm_ksm", "sup_api_cn", "intermediaires", 1.0, 5),
            E("rm_solvents", "sup_api_it", "solvants", 1.0, 5), E("rm_borosilicate", "sup_vials_de", "verre", 1.0, 2),
            E("sup_api_in", "port_nhava_sheva", "api_export", 1.0, 3), E("port_nhava_sheva", "port_antwerp", "fret_api_inde", 1.0, 24),
            E("sup_api_cn", "port_shanghai", "api_export", 1.0, 2), E("port_shanghai", "port_le_havre", "fret_api_chine", 1.0, 32),
            E("port_antwerp", "plant_ff_fr", "api_antibiotique", 0.7, 2), E("port_le_havre", "plant_ff_fr", "api_antibiotique", 0.3, 1, capacity=0.6),
            E("sup_vials_de", "plant_ff_fr", "flacons", 1.0, 3), E("sup_pack_pl", "plant_ff_fr", "emballages", 1.0, 4),
            E("port_antwerp", "plant_oral_ie", "api_antibiotique", 1.0, 4), E("sup_api_it", "plant_oral_ie", "api_antidiabetique", 1.0, 5),
            E("sup_excip_fr", "plant_oral_ie", "excipients", 1.0, 4), E("sup_pack_pl", "plant_oral_ie", "emballages", 1.0, 5),
            E("sup_api_in", "hub_air_cdg", "api_export_air", 0, 2, backup=True, capacity=0.3),
            E("hub_air_cdg", "plant_ff_fr", "api_antibiotique", 0, 1, backup=True, capacity=0.3),
            E("hub_air_cdg", "plant_oral_ie", "api_antibiotique", 0, 2, backup=True, capacity=0.2),
            E("plant_ff_fr", "prod_antibio_inj", "production", 1.0), E("plant_oral_ie", "prod_antibio_oral", "production", 1.0),
            E("plant_oral_ie", "prod_antidiab", "production", 1.0),
        ],
        "gazetteer": [
            {"name": "India", "aliases": ["Inde"], "lat": 20.59, "lon": 78.96, "kind": "pays"},
            {"name": "China", "aliases": ["Chine"], "lat": 35.86, "lon": 104.20, "kind": "pays"},
            {"name": "Belgium", "aliases": ["Belgique"], "lat": 50.50, "lon": 4.47, "kind": "pays"},
            {"name": "France", "aliases": [], "lat": 46.23, "lon": 2.21, "kind": "pays"},
            {"name": "Ireland", "aliases": ["Irlande"], "lat": 53.41, "lon": -8.24, "kind": "pays"},
        ],
        "market_watch": [
            {"id": "API_ANTIBIOTIQUES", "name": "Prix des principes actifs antibiotiques", "yf": "XPH", "nodes": ["sup_api_in", "sup_api_cn"]},
            {"id": "FRET_INDE_EUROPE", "name": "Fret conteneur Inde-Europe", "yf": "BDRY", "nodes": ["port_nhava_sheva"]},
            {"id": "GAZ_EUROPE", "name": "Gaz naturel européen (énergie des verriers)", "yf": "TTF=F", "nodes": ["sup_vials_de"]},
        ],
    },
    "generique": {
        "label": "Gabarit minimal à 9 nœuds : une matière, deux fournisseurs, un port, une usine, un produit",
        "nodes": [
            N("rm_matiere", "Matière première (à renommer)", "matiere_premiere", 4, 0.5, "China", "Shanghai", 31.23, 121.49),
            N("sup_principal", "Fournisseur principal (à renommer)", "fournisseur", 2, 0.8, "China", "Suzhou", 31.30, 120.58, 15, ["Fournisseur principal"], True),
            N("sup_secondaire", "Fournisseur secondaire (à renommer)", "fournisseur", 2, 0.5, "Poland", "Wroclaw", 51.11, 17.04, 15, ["Fournisseur secondaire"], True),
            N("port_depart", "Port of Shanghai", "port", 2, 0.7, "China", "Shanghai", 31.23, 121.49, aliases=["Shanghai port", "port de Shanghai"]),
            N("port_arrivee", "Port of Le Havre", "port", 2, 0.8, "France", "Le Havre", 49.48, 0.13, aliases=["port du Havre", "Le Havre"]),
            N("port_secours", "Port of Antwerp", "port", 2, 0.4, "Belgium", "Antwerp", 51.27, 4.34, aliases=["port d'Anvers", "Antwerp", "Anvers"]),
            N("plant_principale", "{short} (usine principale)", "usine", 1, 0.9, "France", "Lyon", 45.76, 4.84, 15, ["{company}", "usine {short}"], True),
            N("prod_phare", "Produit phare de {short}", "produit_fini", 0, 1.0),
            N("prod_second", "Second produit de {short}", "produit_fini", 0, 0.6),
        ],
        "edges": [
            E("rm_matiere", "sup_principal", "matiere", 1.0, 5), E("rm_matiere", "sup_secondaire", "matiere", 1.0, 40),
            E("sup_principal", "port_depart", "export", 1.0, 2), E("port_depart", "port_arrivee", "fret", 1.0, 32),
            E("port_arrivee", "plant_principale", "composants", 0.8, 2), E("sup_secondaire", "plant_principale", "composants", 0.2, 3, capacity=0.5),
            E("port_depart", "port_secours", "fret_secours", 0, 33, backup=True, capacity=0.5),
            E("port_secours", "plant_principale", "composants", 0, 3, backup=True, capacity=0.5),
            E("plant_principale", "prod_phare", "production", 1.0), E("plant_principale", "prod_second", "production", 1.0),
        ],
        "gazetteer": [
            {"name": "China", "aliases": ["Chine"], "lat": 35.86, "lon": 104.20, "kind": "pays"},
            {"name": "France", "aliases": [], "lat": 46.23, "lon": 2.21, "kind": "pays"},
        ],
        "market_watch": [
            {"id": "FRET_ASIE_EUROPE", "name": "Fret conteneur Asie-Europe", "yf": "BDRY", "nodes": ["port_depart"]},
            {"id": "CUIVRE", "name": "Cuivre", "yf": "HG=F", "nodes": ["rm_matiere"]},
        ],
    },
}

HEADER = """# Topologie générée par scripts/generate_sector_config.py (secteur : {sector}, entreprise : {company}).
#
# POINT DE DÉPART À CORRIGER : les fournisseurs sont inventés. Remplacez-les par les vôtres.
# Sens des liens : source -> target = « source fournit target ».
#   input      : catégorie d'intrant. Plusieurs sources pour une même catégorie = redondance.
#   dependency : part de la catégorie couverte par la source (la somme par catégorie et par cible vaut 1).
#   keywords   : mots-clés sectoriels d'un nœud ; un article qui les contient sans citer de site y est rattaché
#                avec une confiance réduite (mode live).
#   backup     : lien de secours inactif (dependency 0) ; capacity : part maximale activable.
# Vérification : python scripts/generate_sector_config.py --check <ce fichier>

"""


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _fill(value, company: str, short: str):
    if isinstance(value, str):
        return value.replace("{company}", company).replace("{short}", short)
    if isinstance(value, list):
        return [_fill(v, company, short) for v in value]
    if isinstance(value, dict):
        return {k: _fill(v, company, short) for k, v in value.items()}
    return value


def build_topology(sector: str, company: str) -> dict:
    preset = PRESETS[sector]
    short = company.split()[0]
    return {"meta": {"name": f"{preset['label']} ({company})", "sector": sector, "company": company,
                     "simulated_suppliers": True},
            "nodes": _fill(preset["nodes"], company, short), "edges": _fill(preset["edges"], company, short),
            "gazetteer": preset["gazetteer"], "market_watch": preset["market_watch"]}


def topology_yaml(topology: dict) -> str:
    body = yaml.safe_dump(topology, allow_unicode=True, sort_keys=False, default_flow_style=None, width=1000)
    return HEADER.format(sector=topology["meta"]["sector"], company=topology["meta"]["company"]) + body


def build_empty_scenario(engine: OntologyEngine, name: str, topology_ref: str, start: date, days: int) -> dict:
    """Scénario valide mais sans crise : sert de modèle à compléter."""
    rng = random.Random(len(name) + days)
    dmap = day_map(start, days)
    first_hub = engine.weather_hubs()[0].id if engine.weather_hubs() else "<id d'un nœud>"
    return {
        "meta": {"id": f"{name}_modele", "title": f"Modèle vide à compléter ({name})", "fictional": True,
                 "notice": "Scénario modèle sans événement : ajoutez vos articles, vos relevés météo et vos cours.",
                 "topology": topology_ref, "start_date": dmap[1], "days": days,
                 "storyline": {str(k): "À décrire." for k in dmap},
                 "exemples": {
                     "media": {"source_id": f"replay:{name}:001", "published_at": f"{dmap[1]}T08:00:00Z",
                               "language": "French", "title": "Titre de l'article", "text": "Texte ou résumé de l'article."},
                     "weather": {"node_id": first_hub, "date": dmap[min(2, days)], "issued": dmap[1],
                                 "wind_max_kmh": 90, "gust_max_kmh": 140, "precip_mm": 120, "weather_code": 65,
                                 "source_id": f"replay:meteo:{first_hub}:{dmap[min(2, days)]}:prevision-J1"},
                     "finance": "finance.<id d'instrument> : liste de {date, close}, un point par jour, historique inclus"}},
        "media": [],
        "weather": build_weather(engine, dmap, rng),
        "finance": build_finance(engine, start, days, rng),
    }


def check_topology(path: Path) -> int:
    """Charge une topologie et affiche ce qu'un acheteur doit regarder en premier."""
    try:
        engine = OntologyEngine.from_yaml(path)
    except Exception as e:
        print(f"INVALIDE : {path}\n  {type(e).__name__} : {e}")
        return 1
    by_type: dict[str, int] = defaultdict(int)
    for n in engine.nodes.values():
        by_type[n.type] += 1
    print(f"VALIDE : {path}")
    print("  nœuds : " + ", ".join(f"{k} {v}" for k, v in sorted(by_type.items())) + f" (total {len(engine.nodes)})")
    print(f"  liens : {sum(not e.backup for e in engine.edges)} actifs, {sum(e.backup for e in engine.edges)} de secours")
    print(f"  hubs suivis par la météo : {len(engine.weather_hubs())} · instruments financiers : {len(engine.market_watch)}")
    sources: dict[tuple[str, str], list[str]] = defaultdict(list)
    for e in engine.edges:
        sources[(e.target, e.input)].append(e.source)
    single = [(t, i, s[0]) for (t, i), s in sources.items() if len(s) == 1 and engine.nodes[t].type != "produit_fini"]
    print(f"  intrants à source unique, sans secours : {len(single)}")
    for target, inp, source in single:
        print(f"    - {engine.nodes[target].name} dépend de « {engine.nodes[source].name} » pour : {inp}")
    products = [n.id for n in engine.nodes.values() if n.type == "produit_fini"]
    if not products:
        print("  ATTENTION : aucun produit fini. L'indice global et les alertes produit seront vides.")
    orphans = [n.name for n in engine.nodes.values() if engine.graph.degree(n.id) == 0]
    if orphans:
        print("  ATTENTION : nœuds sans aucun lien : " + ", ".join(orphans))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Génère une topologie et un scénario modèle pour un secteur.")
    ap.add_argument("--sector", choices=sorted(PRESETS), help="gabarit de secteur")
    ap.add_argument("--company", default="Votre Entreprise", help="nom de l'entreprise (sert à nommer usines et produits)")
    ap.add_argument("--name", help="nom des fichiers générés (par défaut : secteur + entreprise)")
    ap.add_argument("--data-dir", default=str(ROOT / "data"), help="dossier data/ du projet")
    ap.add_argument("--start-date", default=date.today().isoformat(), help="premier jour du scénario modèle, AAAA-MM-JJ")
    ap.add_argument("--days", type=int, default=7, help="durée du scénario modèle en jours")
    ap.add_argument("--no-scenario", action="store_true", help="n'écrit que la topologie")
    ap.add_argument("--force", action="store_true", help="remplace les fichiers existants")
    ap.add_argument("--list", action="store_true", help="affiche les gabarits disponibles")
    ap.add_argument("--check", metavar="TOPOLOGIE", help="vérifie une topologie existante et affiche ses points faibles")
    args = ap.parse_args(argv)

    if args.list:
        for key, preset in sorted(PRESETS.items()):
            print(f"{key:10s} {len(preset['nodes']):2d} nœuds  {preset['label']}")
        return 0
    if args.check:
        return check_topology(Path(args.check))
    if not args.sector:
        ap.error("--sector est obligatoire (ou --list, ou --check)")
    if not args.company.strip() or args.days < 1:
        ap.error("--company ne peut pas être vide et --days doit valoir au moins 1")
    try:
        start = date.fromisoformat(args.start_date)
    except ValueError:
        ap.error("--start-date : format attendu AAAA-MM-JJ")

    name = slugify(args.name or f"{args.sector}_{args.company}")
    data_dir = Path(args.data_dir)
    topo_path = data_dir / "topologies" / f"{name}.yaml"
    scen_path = data_dir / "replay_scenarios" / f"{name}_modele.json"
    targets = [topo_path] + ([] if args.no_scenario else [scen_path])
    existing = [p for p in targets if p.exists()]
    if existing and not args.force:
        print("Fichiers déjà présents (ajoutez --force pour les remplacer) :\n  " + "\n  ".join(map(str, existing)))
        return 1

    topology = build_topology(args.sector, args.company.strip())
    engine = OntologyEngine(topology)                     # validation avant d'écrire quoi que ce soit
    topo_path.parent.mkdir(parents=True, exist_ok=True)
    topo_path.write_text(topology_yaml(topology), encoding="utf-8")
    print(f"écrit : {topo_path} ({len(engine.nodes)} nœuds, {len(engine.edges)} liens)")
    ref = f"topologies/{name}.yaml"
    if not args.no_scenario:
        scen_path.parent.mkdir(parents=True, exist_ok=True)
        scenario = build_empty_scenario(engine, name, ref, start, args.days)
        scen_path.write_text(json.dumps(scenario, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"écrit : {scen_path} ({args.days} jours, aucun article)")
    print("\nÉtapes suivantes :")
    print(f"  1. Corriger {topo_path.name} avec vos fournisseurs, puis : python scripts/generate_sector_config.py --check {topo_path}")
    if not args.no_scenario:
        print(f"  2. Ajouter des articles, des relevés météo et des cours dans {scen_path.name} (voir meta.exemples).")
        print("  3. Lancer l'interface : le scénario apparaît dans la liste et charge sa topologie tout seul.")
    print(f"  Mode live sur cette chaîne : variable d'environnement SC_TOPOLOGY={ref}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
