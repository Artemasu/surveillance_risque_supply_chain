"""Vue 2 : cartographie, graphe d'ontologie et simulation what-if."""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import networkx as nx  # noqa: E402
import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from app.common import (STRETCH, embed_html, LEVEL_COLORS, LEVEL_LABELS, LEVEL_ORDER, TYPE_LABELS, badge, current_run, ink,  # noqa: E402
                        remember, restore, run_banner, setup_page)

backend = setup_page("Graphe et simulation", "🕸️")
st.title("Graphe d'ontologie et simulation what-if")
run_banner(current_run(backend))        # le graphe s'affiche même sans données : tout est alors au vert

state = backend.graph_state()
nodes = {n["id"]: n for n in state["nodes"]}
edges = state["edges"]
c = ink()

# ------------------------------------------------------------------ panneau what-if
with st.sidebar:
    st.markdown("### Simulation what-if")
    order = {"port": 0, "hub": 1, "fournisseur": 2, "usine": 3, "matiere_premiere": 4, "produit_fini": 5}
    choices = sorted(nodes, key=lambda i: (order[nodes[i]["type"]], nodes[i]["name"]))
    restore("sim_node", "port_kaohsiung" if "port_kaohsiung" in choices else choices[0], lambda v: v in choices)
    restore("sim_severity", 80)
    restore("sim_on", False)
    target = st.selectbox("Nœud perturbé", choices, key="sim_node", on_change=remember, args=("sim_node",),
                          format_func=lambda i: f"{nodes[i]['name']} ({TYPE_LABELS[nodes[i]['type']]})")
    severity = st.slider("Gravité de la panne", 0, 100, step=5, format="%d %%", key="sim_severity", on_change=remember, args=("sim_severity",),
                         help="100 % = arrêt total du nœud.")
    active = st.toggle("Activer la simulation", key="sim_on", on_change=remember, args=("sim_on",),
                       help="L'onde de choc se recalcule à chaque mouvement du curseur. L'état réel n'est pas modifié.")
    remember("sim_node", "sim_severity", "sim_on")

sim = backend.simulate(target, severity / 100) if active else None
shown = {n["id"]: n for n in sim["nodes"]} if sim else nodes

if sim:
    st.markdown(f"**Simulation : {sim['node_name']} perturbé à {severity} %.** L'état réel n'est pas modifié.")
    m = st.columns(3)
    m[0].metric("Indice global simulé", f"{sim['simulated_index']:.1f} / 100",
                delta=f"{sim['simulated_index'] - sim['baseline_index']:+.1f} vs état réel", delta_color="inverse")
    m[1].metric("Nœuds touchés", len(sim["impacts"]))
    m[2].metric("Produits finis menacés", len(sim["threatened_products"]))

# ------------------------------------------------------------------ graphe
SHAPES = {"matiere_premiere": "triangle", "fournisseur": "dot", "port": "square", "hub": "square", "usine": "diamond",
          "produit_fini": "star"}


def build_network_html() -> str:
    from pyvis.network import Network
    dag = nx.DiGraph((e["source"], e["target"]) for e in edges)      # secours compris, pour placer Keelung et le fret aérien
    dag.add_nodes_from(nodes)
    level = {n: i for i, generation in enumerate(nx.topological_generations(dag)) for n in generation}
    net = Network(height="700px", width="100%", directed=True, bgcolor=c["surface"], font_color=c["text"],
                  cdn_resources="in_line")          # JavaScript embarqué : le graphe s'affiche sans Internet
    for nid, n in shown.items():
        delta = n["risk"] - nodes[nid]["risk"]
        title = (f"{n['name']}\n{TYPE_LABELS[n['type']]} · criticité {n['criticality']:.1f}\n"
                 f"Risque {100 * n['risk']:.0f} % ({LEVEL_LABELS[n['level']]})\n"
                 f"direct {100 * n['direct']:.0f} % · propagé {100 * n['propagated']:.0f} %"
                 + (f"\nSimulation : {100 * delta:+.0f} points" if sim and delta > 0.005 else "")
                 + (f"\nStock : {n['stock_days']:.0f} j" if n["stock_days"] else ""))
        net.add_node(nid, label="\n".join(textwrap.wrap(n["name"], 18)) + f"\n{100 * n['risk']:.0f} %", title=title, level=level[nid],
                     shape=SHAPES[n["type"]], size=14 + 16 * n["criticality"],
                     color={"background": LEVEL_COLORS[n["level"]], "border": c["text"] if sim and nid == target else c["surface"]},
                     borderWidth=4 if sim and nid == target else 2, font={"size": 20, "color": c["text"]})
    for e in edges:
        net.add_edge(e["source"], e["target"], width=1 + 6 * e["dependency"], dashes=e["backup"],
                     color=c["muted"] if not e["backup"] else c["axis"],
                     title=(f"{e['input']} · secours, capacité {100 * e['capacity']:.0f} %" if e["backup"]
                            else f"{e['input']} · dépendance {100 * e['dependency']:.0f} %") + f" · délai {e['lead_time_days']:.0f} j")
    net.set_options(json.dumps({
        "layout": {"hierarchical": {"enabled": True, "direction": "LR", "sortMethod": "directed", "levelSeparation": 230,
                                    "nodeSpacing": 125, "treeSpacing": 120}},
        "physics": {"enabled": False},
        "edges": {"smooth": {"type": "cubicBezier", "forceDirection": "horizontal", "roundness": 0.5},
                  "arrows": {"to": {"enabled": True, "scaleFactor": 0.6}}},
        "interaction": {"hover": True, "tooltipDelay": 100, "navigationButtons": False}}))
    return net.generate_html(notebook=False)


tab_graph, tab_map, tab_table = st.tabs(["Graphe", "Carte", "Tableau"])
with tab_graph:
    st.markdown(" ".join(badge(lv) for lv in LEVEL_ORDER) +
                "&nbsp; · &nbsp;épaisseur du lien = dépendance · pointillés = secours inactif · "
                "▲ matière · ● fournisseur · ■ port · ◆ usine · ★ produit fini", unsafe_allow_html=True)
    embed_html(build_network_html(), 730)
    st.caption("Le flux va de gauche (matières premières) à droite (produits finis). Survolez un nœud ou un lien pour le détail.")

with tab_map:
    geo = [n for n in shown.values() if n["lat"] is not None]
    fig = go.Figure()
    for e in edges:
        a, b = nodes[e["source"]], nodes[e["target"]]
        if not e["backup"] and a["lat"] is not None and b["lat"] is not None:
            fig.add_trace(go.Scattergeo(lon=[a["lon"], b["lon"]], lat=[a["lat"], b["lat"]], mode="lines",
                                        line=dict(width=0.5 + 2 * e["dependency"], color=c["muted"]),
                                        opacity=0.55, hoverinfo="skip", showlegend=False))
    for lv in LEVEL_ORDER:
        sub = [n for n in geo if n["level"] == lv]
        if sub:
            fig.add_trace(go.Scattergeo(
                lon=[n["lon"] for n in sub], lat=[n["lat"] for n in sub], mode="markers", name=LEVEL_LABELS[lv],
                marker=dict(size=[9 + 9 * n["criticality"] for n in sub], color=LEVEL_COLORS[lv],
                            line=dict(width=2, color=c["surface"])),
                customdata=[[n["name"], TYPE_LABELS[n["type"]], 100 * n["risk"], n["place"] or ""] for n in sub],
                hovertemplate="%{customdata[0]} (%{customdata[1]})<br>%{customdata[3]}<br>Risque : %{customdata[2]:.0f} %<extra></extra>"))
    fig.update_geos(projection_type="natural earth", showland=True, landcolor=c["grid"], showocean=True,
                    oceancolor=c["surface"], showcountries=True, countrycolor=c["axis"], coastlinecolor=c["axis"],
                    bgcolor="rgba(0,0,0,0)", lataxis_range=[-35, 65])
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", font=dict(color=c["text"]), height=560, margin=dict(l=0, r=0, t=0, b=0),
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0))
    st.plotly_chart(fig, **STRETCH)
    st.caption("Sites géolocalisés. Le fond de carte est téléchargé par le navigateur : hors ligne, seuls les points et les liens s'affichent.")

with tab_table:
    df = pd.DataFrame([{"Nœud": n["name"], "Type": TYPE_LABELS[n["type"]], "Niveau": LEVEL_LABELS[n["level"]],
                        "Risque (%)": round(100 * n["risk"]), "Direct (%)": round(100 * n["direct"]),
                        "Propagé (%)": round(100 * n["propagated"]), "Criticité": n["criticality"],
                        "Stock (j)": n["stock_days"], "Chemin": " → ".join(nodes[i]["name"] for i in n["path"])}
                       for n in sorted(shown.values(), key=lambda n: -n["risk"])])
    st.dataframe(df, hide_index=True, **STRETCH, height=520)

# ------------------------------------------------------------------ détail de la simulation
if sim:
    left, right = st.columns([3, 2])
    with left:
        st.subheader("Onde de choc")
        if sim["impacts"]:
            st.dataframe(pd.DataFrame([{"Nœud": i["name"], "Type": TYPE_LABELS[i["type"]],
                                        "Avant (%)": round(100 * i["baseline"]), "Après (%)": round(100 * i["simulated"]),
                                        "Écart (points)": round(100 * i["delta"]), "Niveau simulé": LEVEL_LABELS[i["level"]],
                                        "Chemin": " → ".join(nodes[p]["name"] for p in i["path"])} for i in sim["impacts"]]),
                         hide_index=True, **STRETCH)
        else:
            st.info("Aucun impact supplémentaire : ce nœud est déjà au moins aussi dégradé dans l'état réel.")
    with right:
        st.subheader("Plan de contournement")
        plan = sim["mitigation"]
        titles = {"reallocation": "Réallouer", "route_secours": "Route de secours", "stock": "Stocks", "surveillance": "Surveillance"}
        for i, a in enumerate(plan["actions"], start=1):
            st.markdown(f"{i}. **{titles[a['kind']]}** : {a['description']}")
        for key, cov in plan["coverage"].items():
            st.progress(min(1.0, cov), text=f"{key} : {100 * cov:.0f} % du besoin récupérable")
        st.caption("Capacités et délais issus de la topologie (données simulées).")
