"""Exporte les figures de soutenance en PNG haute résolution dans docs/figures/.

    python scripts/export_soutenance.py
    python scripts/export_soutenance.py --scenario crisis_pharma_api --node plant_ff_fr --dpi 200

Figures produites (scénario crisis_asia_semiconductors par défaut) :
  indice_global_<scénario>.png   évolution de l'indice de risque global, du premier au dernier jour ;
  anticipation_<nœud>.png        risque de l'usine vu par le graphe, comparé au moment où la presse la cite.
Tout est recalculé en rejouant le scénario jour par jour : aucun chiffre n'est écrit en dur dans ce script.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")                       # rendu sans écran
import matplotlib.pyplot as plt  # noqa: E402

from src.graph.ontology_engine import ALERT_THRESHOLD  # noqa: E402
from src.schemas.events import PipelineRunRequest  # noqa: E402
from src.service import SupplyChainService  # noqa: E402

# Palette : une teinte par série, encres neutres pour le texte, grille discrète.
BLUE, ORANGE = "#2a78d6", "#eb6834"
INK, INK_2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def replay(scenario: str, node_id: str) -> dict:
    """Rejoue le scénario jour par jour et relève l'indice global et le risque du nœud suivi."""
    service = SupplyChainService()
    meta = next((s for s in service.list_scenarios() if s["id"] == scenario), None)
    if meta is None:
        sys.exit(f"scénario introuvable : {scenario}")
    rows = []
    for day in range(1, int(meta["days"]) + 1):
        run = asyncio.run(service.run_pipeline(PipelineRunRequest(mode="replay", scenario=scenario, day=day)))
        if node_id not in service.engine.nodes:
            sys.exit(f"nœud inconnu dans la topologie de ce scénario : {node_id}")
        node = next(n for n in service.engine.state().nodes if n.id == node_id)
        cited = [m.source_id for e in service.engine.events if e.meta.agent == "media"
                 and node_id in service.engine.current.links.get(e.event.id, []) for m in e.media]
        y, m, d = run.as_of.split("-")
        rows.append({"day": day, "date": run.as_of, "label": f"J{day}\n{int(d)} {MONTHS[int(m) - 1]}",
                     "index": run.global_risk_index, "risk": 100 * node.risk, "direct": 100 * node.direct,
                     "propagated": 100 * node.propagated, "articles": len(cited), "origin": node.path[0]})
    names = {n.id: n.name for n in service.engine.nodes.values()}
    return {"meta": meta, "rows": rows, "node_name": names[node_id], "names": names}


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=INK_2, length=0, labelsize=10)


def _titles(fig, title: str, subtitle: str) -> None:
    fig.text(0.06, 0.955, title, fontsize=15, fontweight="bold", color=INK, ha="left", va="top")
    fig.text(0.06, 0.895, subtitle, fontsize=10.5, color=INK_2, ha="left", va="top")


def figure_index(data: dict, out: Path, dpi: int) -> Path:
    rows = data["rows"]
    x, y = [r["day"] for r in rows], [r["index"] for r in rows]
    fig, ax = plt.subplots(figsize=(10, 5.6), facecolor=SURFACE)
    fig.subplots_adjust(left=0.06, right=0.97, top=0.80, bottom=0.20)
    _style(ax)
    ax.plot(x, y, color=BLUE, linewidth=2, marker="o", markersize=8, markeredgecolor=SURFACE, markeredgewidth=2, zorder=3)
    for xi, yi in zip(x, y):
        ax.annotate(f"{yi:.1f}".replace(".", ","), (xi, yi), textcoords="offset points", xytext=(0, 11), ha="center",
                    fontsize=10.5, color=INK, fontweight="bold")
    ax.set_xticks(x, [r["label"] for r in rows])
    ax.set_xlim(x[0] - 0.4, x[-1] + 0.4)
    ax.set_ylim(0, max(y) * 1.25)
    ax.set_ylabel("Indice de risque global (sur 100)", color=INK_2, fontsize=10)
    _titles(fig, f"L'indice de risque global passe de {y[0]:.0f} à {y[-1]:.0f} en {len(rows)} jours",
            f"{data['meta']['title']} · chaque point est recalculé avec ce qui était connu ce jour-là")
    story = data["meta"].get("storyline", {})
    notes = "\n".join(f"J{r['day']} : {story[str(r['day'])]}" for r in rows if str(r["day"]) in story)
    fig.text(0.06, 0.005, "Scénario fictif écrit pour la démonstration.", fontsize=8.5, color=MUTED, ha="left", va="bottom")
    path = out / f"indice_global_{data['meta']['id']}.png"
    fig.savefig(path, dpi=dpi, facecolor=SURFACE)
    plt.close(fig)
    (out / f"indice_global_{data['meta']['id']}.txt").write_text(notes + "\n", encoding="utf-8")   # légende jour par jour
    return path


def figure_anticipation(data: dict, node_id: str, out: Path, dpi: int) -> tuple[Path, dict]:
    rows = data["rows"]
    x = [r["day"] for r in rows]
    alert = next((r for r in rows if r["risk"] >= 100 * ALERT_THRESHOLD), None)
    article = next((r for r in rows if r["articles"] > 0), None)
    lead = article["day"] - alert["day"] if alert and article else None

    fig, ax = plt.subplots(figsize=(10, 5.8), facecolor=SURFACE)
    fig.subplots_adjust(left=0.07, right=0.77, top=0.80, bottom=0.17)
    _style(ax)
    if lead and lead > 0:
        ax.axvspan(alert["day"], article["day"], color=BLUE, alpha=0.08, linewidth=0, zorder=0)
        ax.annotate("", xy=(article["day"], 92), xytext=(alert["day"], 92),
                    arrowprops=dict(arrowstyle="<->", color=INK_2, linewidth=1.2))
        ax.text((alert["day"] + article["day"]) / 2, 95, f"{lead} jour{'s' if lead > 1 else ''} d'avance",
                ha="center", va="bottom", fontsize=11, fontweight="bold", color=INK)
    ax.axhline(100 * ALERT_THRESHOLD, color=MUTED, linewidth=1, linestyle=(0, (4, 3)), zorder=1)
    ax.text(x[-1] + 0.45, 100 * ALERT_THRESHOLD, f"seuil d'alerte\n({100 * ALERT_THRESHOLD:.0f} %)", va="center",
            ha="left", fontsize=9.5, color=INK_2)
    series = [("risk", "Risque calculé\npar le graphe", BLUE, "o"),
              ("direct", "Risque direct : articles\nqui citent l'usine", ORANGE, "s")]
    for key, name, color, marker in series:
        ys = [r[key] for r in rows]
        ax.plot(x, ys, color=color, linewidth=2, marker=marker, markersize=8, markeredgecolor=SURFACE,
                markeredgewidth=2, zorder=3, label=name)
    if alert:
        ax.annotate(f"J{alert['day']} : alerte par propagation\n({alert['risk']:.0f} %, aucun article sur l'usine)",
                    (alert["day"], alert["risk"]), textcoords="offset points", xytext=(26, -46), ha="left", va="top",
                    fontsize=9.5, color=INK, arrowprops=dict(arrowstyle="-", color=AXIS, linewidth=1))
    if article:
        ax.annotate(f"J{article['day']} : premier article\nqui cite l'usine", (article["day"], article["direct"]),
                    textcoords="offset points", xytext=(-75, -22), ha="right", va="top", fontsize=9.5, color=INK,
                    arrowprops=dict(arrowstyle="-", color=AXIS, linewidth=1))
    ax.set_xticks(x, [r["label"] for r in rows])
    ax.set_xlim(x[0] - 0.4, x[-1] + 0.4)
    ax.set_ylim(0, 105)
    ax.set_yticks(range(0, 101, 20), [f"{v} %" for v in range(0, 101, 20)])
    ax.legend(loc="upper left", frameon=False, fontsize=9.5, labelcolor=INK, bbox_to_anchor=(1.01, 1.0),
              labelspacing=1.0, handlelength=1.8)       # légende dans la marge droite, hors du tracé
    origin = data["names"].get(alert["origin"], "") if alert else ""
    head = (f"Le graphe alerte sur {data['node_name'].split(' (')[0]} {lead} jour{'s' if lead and lead > 1 else ''} avant la presse"
            if lead and lead > 0 else f"Risque de {data['node_name'].split(' (')[0]} : graphe et presse")
    _titles(fig, head, f"Le risque vient de l'amont ({origin}) et se propage le long des liens du graphe"
            if origin else data["meta"]["title"])
    fig.text(0.07, 0.005, "Scénario fictif écrit pour la démonstration : cette avance n'est pas une mesure de performance.",
             fontsize=8.5, color=MUTED, ha="left", va="bottom")
    path = out / f"anticipation_{node_id}.png"
    fig.savefig(path, dpi=dpi, facecolor=SURFACE)
    plt.close(fig)
    return path, {"alert_day": alert["day"] if alert else None, "article_day": article["day"] if article else None, "lead": lead}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Exporte les figures de soutenance (PNG).")
    ap.add_argument("--scenario", default="crisis_asia_semiconductors")
    ap.add_argument("--node", default="plant_ecu_de", help="nœud suivi dans la figure d'anticipation")
    ap.add_argument("--out", default=str(ROOT / "docs" / "figures"))
    ap.add_argument("--dpi", type=int, default=300)
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    data = replay(args.scenario, args.node)
    p1 = figure_index(data, out, args.dpi)
    p2, facts = figure_anticipation(data, args.node, out, args.dpi)
    print(f"écrit : {p1}\nécrit : {p2}")
    print("indice par jour : " + ", ".join(f"J{r['day']} {r['index']}" for r in data["rows"]))
    print(f"{data['node_name']} : première alerte J{facts['alert_day']}, premier article J{facts['article_day']}, "
          f"avance {facts['lead']} jour(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
