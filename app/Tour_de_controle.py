"""Vue 1 : Tour de contrôle (tableau de bord exécutif).

    streamlit run app/Tour_de_controle.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from app.common import (STRETCH, AGENT_COLORS, AGENT_LABELS, LEVEL_COLORS, LEVEL_LABELS, TYPE_LABELS, current_run, ink,  # noqa: E402
                        run_banner, setup_page)

backend = setup_page("Tour de contrôle", "🛰️")
st.title("Tour de contrôle")
run = current_run(backend)
if not run_banner(run):
    st.stop()

state, alerts, events = backend.graph_state(), backend.alerts(), backend.events()
c = ink()

# ------------------------------------------------------------------ indicateurs
timeline = run.get("timeline", [])
previous = timeline[-2]["global_risk_index"] if len(timeline) >= 2 else None
by_agent = {a: 0 for a in AGENT_LABELS}
for s in events["signals"]:
    for a in s["agents"]:
        by_agent[a] += 1

k = st.columns(3)
k[0].metric("Indice de risque global (sur 100)", f"{state['global_risk_index']:.1f}",
            delta=None if previous is None else f"{state['global_risk_index'] - previous:+.1f} vs veille", delta_color="inverse")
k[1].metric("Nœuds critiques", len(state["critical_nodes"]))
k[2].metric("Alertes actives", len(alerts))
k = st.columns(3)
for col, agent in zip(k, AGENT_LABELS):
    col.metric(f"Signaux {AGENT_LABELS[agent]}", by_agent[agent],
               help="Nombre de signaux corrélés auxquels cet agent contribue.")

layout = dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color=c["text"]),
              margin=dict(l=10, r=10, t=10, b=10), hoverlabel=dict(font_size=13))

left, right = st.columns([3, 2])
with left:
    st.subheader("Indice de risque global par jour")
    if timeline:
        fig = go.Figure(go.Scatter(
            x=[p["date"] for p in timeline], y=[p["global_risk_index"] for p in timeline], mode="lines+markers",
            line=dict(color="#3987e5", width=2), marker=dict(size=8),
            customdata=[p["n_events"] for p in timeline],
            hovertemplate="%{x}<br>Indice : %{y:.1f} / 100<br>Événements connus : %{customdata}<extra></extra>"))
        fig.update_layout(**layout, height=300, showlegend=False)
        fig.update_yaxes(rangemode="tozero", gridcolor=c["grid"], zeroline=False, title="Indice / 100")
        fig.update_xaxes(type="category", showgrid=False, linecolor=c["axis"])
        st.plotly_chart(fig, **STRETCH)
        if run["mode"] == "replay":
            st.caption("Chaque point est recalculé avec ce qui était connu ce jour-là.")

with right:
    st.subheader("Nœuds les plus exposés")
    top = sorted([n for n in state["nodes"] if n["risk"] > 0.01], key=lambda n: n["risk"], reverse=True)[:8][::-1]
    if top:
        fig = go.Figure(go.Bar(
            x=[100 * n["risk"] for n in top], y=[n["name"] for n in top], orientation="h",
            marker=dict(color=[LEVEL_COLORS[n["level"]] for n in top], line=dict(width=0)),
            text=[f"{100 * n['risk']:.0f} % · {LEVEL_LABELS[n['level']]}" for n in top], textposition="auto",
            customdata=[[TYPE_LABELS[n["type"]], 100 * n["direct"], 100 * n["propagated"]] for n in top],
            hovertemplate="%{y} (%{customdata[0]})<br>Risque : %{x:.0f} %<br>Direct : %{customdata[1]:.0f} % · "
                          "Propagé : %{customdata[2]:.0f} %<extra></extra>"))
        fig.update_layout(**layout, height=300, showlegend=False, bargap=0.25)
        fig.update_xaxes(range=[0, 100], gridcolor=c["grid"], ticksuffix=" %")
        fig.update_yaxes(showgrid=False)
        st.plotly_chart(fig, **STRETCH)
    else:
        st.write("Aucun nœud exposé.")

# ------------------------------------------------------------------ chronologie des signaux
st.subheader("Chronologie des signaux")
rows = [{"date": e["event"]["date"], "agent": e["agent"], "type": e["event"]["event"]["type"],
         "label": e["event"]["event"]["label"], "noeuds": ", ".join(e["node_names"]) or "non rattaché au graphe"}
        for e in events["events"] if e["event"]["date"]]
if rows:
    df = pd.DataFrame(rows)
    dates = sorted({p["date"] for p in timeline} | set(df["date"]))
    fig = go.Figure()
    for agent, label in AGENT_LABELS.items():
        grouped = df[df["agent"] == agent].groupby("date")
        xs = list(grouped.groups)
        counts = [len(grouped.get_group(d)) for d in xs]
        linked = [any(n != "non rattaché au graphe" for n in grouped.get_group(d)["noeuds"]) for d in xs]
        hover = ["<br>".join(f"{r.type} · {r.label[:90]}<br>   nœuds : {r.noeuds}" for r in grouped.get_group(d).itertuples()) for d in xs]
        fig.add_trace(go.Scatter(
            x=xs, y=[label] * len(xs), mode="markers+text", name=label, text=[str(n) if n > 1 else "" for n in counts],
            textfont=dict(color="#ffffff", size=12),
            marker=dict(size=[16 + 5 * min(n - 1, 4) for n in counts], color=AGENT_COLORS[agent],
                        line=dict(width=2, color=c["surface"]), symbol=["circle" if ok else "circle-open" for ok in linked]),
            customdata=hover, hovertemplate="%{x} · " + label + "<br>%{customdata}<extra></extra>"))
    fig.update_layout(**layout, height=230, legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    fig.update_xaxes(type="category", categoryorder="array", categoryarray=dates, gridcolor=c["grid"])
    fig.update_yaxes(showgrid=False, categoryorder="array", categoryarray=list(AGENT_LABELS.values())[::-1])
    st.plotly_chart(fig, **STRETCH)
    st.caption("Un point par jour et par agent ; le chiffre indique le nombre d'événements. Cercle vide : événements détectés "
               "mais non rattachés à un nœud du graphe (signal faible).")
else:
    st.write("Aucun événement daté.")

# ------------------------------------------------------------------ agents
st.subheader("État des agents")
status_fr = {"success": "OK", "error": "En panne"}
st.dataframe(pd.DataFrame([
    {"Agent": AGENT_LABELS.get(name, name), "État": status_fr.get(a["status"], a["status"]) + (" (incomplet)" if a["degraded"] else ""),
     "Événements": a["count"], "Détail": a["message"],
     "Sources": ", ".join(f"{k} : {v.get('status')}" for k, v in a["sources"].items())}
    for name, a in run["agents"].items()]), hide_index=True, **STRETCH)
st.caption(run["message"])
