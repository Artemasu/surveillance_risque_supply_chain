"""Inscription d'un nouveau client : de la fiche saisie à une topologie prête pour le pipeline.

Principes de protection des données (RGPD) appliqués ici :
  - minimisation : seules les coordonnées professionnelles d'un interlocuteur sont demandées ;
  - séparation : les données personnelles (data/clients/) ne figurent jamais dans la topologie ni dans le
    scénario ; la topologie ne porte qu'un identifiant client aléatoire ;
  - confidentialité des affaires : les noms de fournisseurs peuvent être remplacés par des pseudonymes ;
  - preuve du consentement : version de la notice et horodatage conservés avec la fiche ;
  - droits des personnes : export (portabilité) et suppression complète (effacement) par identifiant ;
  - aucun fichier client n'est suivi par Git (voir .gitignore).
Les lieux (ville, pays) sont géocodés par Open-Meteo : seuls des noms de lieux quittent le serveur.
"""
from __future__ import annotations

import json
import re
import secrets
import string
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scripts.generate_sector_config import PRESETS, build_empty_scenario, build_topology, slugify, topology_yaml
from src.graph.ontology_engine import OntologyEngine

NOTICE_VERSION = "2026-11-v1"          # à incrémenter à chaque modification de la notice affichée
DUREE_CONSERVATION_JOURS = 3 * 365      # sans activité, la fiche est supprimée (recommandation CNIL : 3 ans)
PREFIXE = "client_"                     # préfixe des fichiers générés, exclus de Git
SCENARIO_JOURS = 7

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[A-Za-z]{2,}$")
_GRATUITS = {"gmail.com", "yahoo.com", "yahoo.fr", "hotmail.com", "hotmail.fr", "outlook.com", "outlook.fr",
             "live.com", "live.fr", "icloud.com", "laposte.net", "orange.fr", "free.fr", "sfr.fr", "wanadoo.fr"}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _texte():
    return Field(min_length=1, max_length=120)


class Entreprise(Strict):
    raison_sociale: str = Field(min_length=2, max_length=120)
    secteur: str = Field(min_length=2, max_length=80)          # libellé libre (pharmacie, automobile...)
    pays: str = _texte()
    taille: Literal["TPE", "PME", "ETI", "Grande entreprise"]


class Lieu(Strict):
    nom: str = _texte()
    ville: str = _texte()
    pays: str = _texte()


class Site(Lieu):
    stock_jours: int = Field(default=15, ge=0, le=365)


class PointLogistique(Lieu):
    type: Literal["port", "hub"] = "port"


class Fournisseur(Lieu):
    categorie: str = Field(min_length=1, max_length=60)        # ce qu'il fournit : « principe actif », « verre »...
    site: str = _texte()                                          # site livré (nom d'un site)
    part_pct: float = Field(default=100, gt=0, le=100)         # part de cette catégorie couverte pour ce site
    passage: Optional[str] = Field(default=None, max_length=120)   # point logistique emprunté (facultatif)
    stock_jours: int = Field(default=15, ge=0, le=365)
    critique: bool = False                                     # fournisseur difficile à remplacer


class Produit(Strict):
    nom: str = _texte()
    site: str = _texte()


class Chaine(Strict):
    sites: list[Site] = Field(min_length=1, max_length=20)
    fournisseurs: list[Fournisseur] = Field(min_length=1, max_length=60)
    points_logistiques: list[PointLogistique] = Field(default_factory=list, max_length=20)
    produits: list[Produit] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def references(self) -> "Chaine":
        sites = {s.nom for s in self.sites}
        points = {p.nom for p in self.points_logistiques}
        noms = [x.nom for x in (*self.sites, *self.points_logistiques, *self.fournisseurs)]
        doublons = {n for n in noms if noms.count(n) > 1}
        if doublons:
            raise ValueError(f"noms en double : {', '.join(sorted(doublons))}")
        for f in self.fournisseurs:
            if f.site not in sites:
                raise ValueError(f"fournisseur « {f.nom} » : site inconnu « {f.site} »")
            if f.passage and f.passage not in points:
                raise ValueError(f"fournisseur « {f.nom} » : point logistique inconnu « {f.passage} »")
        for p in self.produits:
            if p.site not in sites:
                raise ValueError(f"produit « {p.nom} » : site inconnu « {p.site} »")
        return self


class Contact(Strict):
    prenom: str = Field(min_length=1, max_length=60)
    nom: str = Field(min_length=1, max_length=60)
    email: str = Field(max_length=120)
    fonction: Optional[str] = Field(default=None, max_length=80)

    @field_validator("email")
    @classmethod
    def email_professionnel(cls, v: str) -> str:
        v = v.lower()
        if not _EMAIL.match(v):
            raise ValueError("adresse e-mail invalide")
        if v.split("@")[1] in _GRATUITS:
            raise ValueError("merci d'indiquer une adresse e-mail professionnelle")
        return v


class Consentements(Strict):
    traitement: bool                 # a pris connaissance de la notice et accepte le traitement décrit
    habilitation: bool               # est habilité à communiquer ces informations pour son entreprise
    version_notice: str

    @model_validator(mode="after")
    def obligatoires(self) -> "Consentements":
        if not (self.traitement and self.habilitation):
            raise ValueError("les deux confirmations sont nécessaires pour créer l'espace client")
        if self.version_notice != NOTICE_VERSION:
            raise ValueError("la notice d'information a changé : rechargez la page")
        return self


class Inscription(Strict):
    entreprise: Entreprise
    contact: Contact
    gabarit: Optional[str] = None                 # clé de PRESETS : chaîne type à compléter plus tard
    chaine: Optional[Chaine] = None               # chaîne décrite par le client
    pseudonymiser_fournisseurs: bool = True
    consentements: Consentements

    @model_validator(mode="after")
    def une_chaine(self) -> "Inscription":
        if (self.gabarit is None) == (self.chaine is None):
            raise ValueError("choisir soit un gabarit sectoriel, soit la description de la chaîne")
        if self.gabarit is not None and self.gabarit not in PRESETS:
            raise ValueError(f"gabarit inconnu : {self.gabarit}")
        return self


class InscriptionResultat(BaseModel):
    client_id: str
    topology_ref: str
    scenario_id: str
    noeuds: int
    liens: int
    points_faibles: list[str]
    conservation_jusqu_au: str


def gabarits() -> list[dict]:
    return [{"id": k, "label": v["label"], "noeuds": len(v["nodes"])} for k, v in sorted(PRESETS.items())]


# --------------------------------------------------------------------------- construction de la topologie
def _id(prefixe: str, texte: str, pris: set[str]) -> str:
    base = f"{prefixe}_{slugify(texte)[:30] or 'x'}"
    nid, i = base, 2
    while nid in pris:
        nid, i = f"{base}_{i}", i + 1
    pris.add(nid)
    return nid


def _pseudo(i: int) -> str:
    lettres = string.ascii_uppercase
    return f"Fournisseur {lettres[i % 26]}{'' if i < 26 else i // 26}"


def topologie_personnalisee(ins: Inscription, geocoder: Callable[[str, str], dict]) -> dict:
    """Topologie à partir de la chaîne saisie. `geocoder(ville, pays)` -> {"lat", "lon"}."""
    ch, pris = ins.chaine, set()
    nodes, edges = [], []

    def lieu(x: Lieu, nid: str, name: str, type_: str, tier: int, crit: float, **extra) -> dict:
        g = geocoder(x.ville, x.pays)
        node = {"id": nid, "name": name, "type": type_, "tier": tier, "criticality": crit, "country": x.pays,
                "place": x.ville, "lat": round(float(g["lat"]), 3), "lon": round(float(g["lon"]), 3),
                "weather_watch": True, **extra}
        nodes.append(node)
        return node

    id_site = {s.nom: _id("plant", s.nom, pris) for s in ch.sites}
    for s in ch.sites:
        lieu(s, id_site[s.nom], s.nom, "usine", 1, 0.9, stock_days=s.stock_jours, company=True,
             aliases=[f"{s.nom} ({s.ville})"])
    id_point = {p.nom: _id(p.type, p.nom, pris) for p in ch.points_logistiques}
    for p in ch.points_logistiques:
        lieu(p, id_point[p.nom], p.nom, p.type, 2, 0.7, aliases=[p.ville])

    # Parts par (site, catégorie) ramenées à 1 : la somme saisie n'a pas besoin de faire 100 %.
    total = defaultdict(float)
    for f in ch.fournisseurs:
        total[(f.site, f.categorie)] += f.part_pct
    via_point = defaultdict(float)             # (point, site, catégorie) -> part transitant par le point
    for i, f in enumerate(ch.fournisseurs):
        nid = _id("sup", f.nom if not ins.pseudonymiser_fournisseurs else f"fournisseur_{i}", pris)
        nom = _pseudo(i) + f" ({f.categorie})" if ins.pseudonymiser_fournisseurs else f.nom
        lieu(f, nid, nom, "fournisseur", 2, 0.9 if f.critique else 0.6, stock_days=f.stock_jours,
             company=not ins.pseudonymiser_fournisseurs, aliases=[] if ins.pseudonymiser_fournisseurs else [f.nom])
        part = f.part_pct / total[(f.site, f.categorie)]
        if f.passage:
            via_point[(f.passage, f.site, f.categorie)] += part
            edges.append({"_source": nid, "_point": f.passage, "_site": f.site, "_cat": f.categorie, "_part": part})
        else:
            edges.append({"source": nid, "target": id_site[f.site], "input": f.categorie,
                          "dependency": round(part, 4), "lead_time_days": 0})
    final = []
    for e in edges:
        if "_point" not in e:
            final.append(e)
            continue
        cle = (e["_point"], e["_site"], e["_cat"])
        final.append({"source": e["_source"], "target": id_point[e["_point"]], "input": f"{e['_cat']} ({e['_site']})",
                      "dependency": round(e["_part"] / via_point[cle], 4), "lead_time_days": 0})
    for (point, site, cat), part in via_point.items():
        final.append({"source": id_point[point], "target": id_site[site], "input": cat,
                      "dependency": round(part, 4), "lead_time_days": 0})
    for p in ch.produits:
        nid = _id("prod", p.nom, pris)
        nodes.append({"id": nid, "name": p.nom, "type": "produit_fini", "tier": 0, "criticality": 0.8, "aliases": []})
        final.append({"source": id_site[p.site], "target": nid, "input": "production", "dependency": 1.0,
                      "lead_time_days": 0})
    _arrondi_exact(final)
    return {"nodes": nodes, "edges": final, "gazetteer": [], "market_watch": []}


def _arrondi_exact(edges: list[dict]) -> None:
    """Après arrondi, la somme des parts par (cible, intrant) doit valoir exactement 1 (contrôle du moteur)."""
    groupes = defaultdict(list)
    for e in edges:
        groupes[(e["target"], e["input"])].append(e)
    for liste in groupes.values():
        ecart = 1.0 - sum(e["dependency"] for e in liste)
        max(liste, key=lambda e: e["dependency"])["dependency"] = round(
            max(liste, key=lambda e: e["dependency"])["dependency"] + ecart, 10)


# --------------------------------------------------------------------------- enregistrement et droits
class Registre:
    """Fichiers d'un client : fiche (données personnelles), topologie et scénario modèle (sans donnée personnelle)."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.dossier_fiches = self.data_dir / "clients"

    def _chemins(self, client_id: str) -> dict[str, Path]:
        if not re.fullmatch(r"[a-z0-9]{16}", client_id or ""):
            raise KeyError(client_id)
        nom = f"{PREFIXE}{client_id}"
        return {"fiche": self.dossier_fiches / f"{client_id}.json",
                "topologie": self.data_dir / "topologies" / f"{nom}.yaml",
                "scenario": self.data_dir / "replay_scenarios" / f"{nom}_modele.json"}

    def inscrire(self, ins: Inscription, geocoder: Callable[[str, str], dict]) -> InscriptionResultat:
        client_id = secrets.token_hex(8)                     # aléatoire : ne révèle ni l'entreprise ni l'ordre
        chemins = self._chemins(client_id)
        societe = ins.entreprise.raison_sociale
        if ins.gabarit:
            topo = build_topology(ins.gabarit, societe)
            topo["meta"]["simulated_suppliers"] = True
        else:
            topo = topologie_personnalisee(ins, geocoder)
            topo["meta"] = {"name": f"{societe} : chaîne déclarée à l'inscription", "sector": ins.entreprise.secteur,
                            "company": societe, "simulated_suppliers": False}
        topo["meta"].update(client_id=client_id, pseudonymized_suppliers=bool(ins.chaine and ins.pseudonymiser_fournisseurs))
        topo = {"meta": topo.pop("meta"), **topo}
        engine = OntologyEngine(topo)                        # validation avant toute écriture

        ref = f"topologies/{chemins['topologie'].name}"
        scenario = build_empty_scenario(engine, f"{PREFIXE}{client_id}", ref, date.today(), SCENARIO_JOURS)
        scenario["meta"]["title"] = f"{societe} : scénario modèle à compléter"
        maintenant = datetime.now(timezone.utc)
        fiche = {
            "client_id": client_id,
            "cree_le": maintenant.isoformat(timespec="seconds"),
            "conservation_jusqu_au": (maintenant + timedelta(days=DUREE_CONSERVATION_JOURS)).date().isoformat(),
            "entreprise": ins.entreprise.model_dump(),
            "contact": ins.contact.model_dump(),
            "consentements": {**ins.consentements.model_dump(), "horodatage": maintenant.isoformat(timespec="seconds")},
            "topologie": ref,
            "scenario": chemins["scenario"].stem,
        }
        for cle, contenu in (("topologie", topology_yaml(topo)),
                             ("scenario", json.dumps(scenario, ensure_ascii=False, indent=1)),
                             ("fiche", json.dumps(fiche, ensure_ascii=False, indent=1))):
            chemins[cle].parent.mkdir(parents=True, exist_ok=True)
            chemins[cle].write_text(contenu, encoding="utf-8")
        return InscriptionResultat(client_id=client_id, topology_ref=ref, scenario_id=chemins["scenario"].stem,
                                   noeuds=len(engine.nodes), liens=len(engine.edges),
                                   points_faibles=points_faibles(engine),
                                   conservation_jusqu_au=fiche["conservation_jusqu_au"])

    def exporter(self, client_id: str) -> dict:
        """Droit d'accès et de portabilité : tout ce qui est conservé pour ce client."""
        c = self._chemins(client_id)
        if not c["fiche"].exists():
            raise KeyError(client_id)
        return {"fiche": json.loads(c["fiche"].read_text(encoding="utf-8")),
                "topologie": c["topologie"].read_text(encoding="utf-8") if c["topologie"].exists() else None}

    def supprimer(self, client_id: str) -> list[str]:
        """Droit à l'effacement : fiche, topologie et scénario."""
        supprimes = []
        for chemin in self._chemins(client_id).values():
            if chemin.exists():
                chemin.unlink()
                supprimes.append(chemin.name)
        if not supprimes:
            raise KeyError(client_id)
        return supprimes

    def purger(self, aujourd_hui: Optional[date] = None) -> list[str]:
        """Supprime les fiches dont la durée de conservation est dépassée (à planifier)."""
        aujourd_hui = aujourd_hui or date.today()
        purges = []
        for fiche in self.dossier_fiches.glob("*.json"):
            try:
                limite = date.fromisoformat(json.loads(fiche.read_text(encoding="utf-8"))["conservation_jusqu_au"])
            except (OSError, ValueError, KeyError):
                continue
            if limite < aujourd_hui:
                self.supprimer(fiche.stem)
                purges.append(fiche.stem)
        return purges


def points_faibles(engine: OntologyEngine) -> list[str]:
    """Intrants à source unique : ce que le client doit regarder en premier."""
    sources = defaultdict(list)
    for e in engine.edges:
        if not e.backup:
            sources[(e.target, e.input)].append(e.source)
    return [f"{engine.nodes[t].name} dépend d'une seule source pour « {i} » : {engine.nodes[s[0]].name}"
            for (t, i), s in sources.items() if len(s) == 1 and engine.nodes[t].type != "produit_fini"
            and engine.nodes[s[0]].type == "fournisseur"]
