"""Vue 3 : flux d'alertes et preuves multi-sources."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app.common import STRETCH, AGENT_LABELS, LEVEL_LABELS, badge, current_run, run_banner, setup_page  # noqa: E402

backend = setup_page("Alertes et preuves", "🚨")
st.title("Alertes et preuves multi-sources")
if not run_banner(current_run(backend)):
    st.stop()

alerts, payload = backend.alerts(), backend.events()
events, signals = payload["events"], payload["signals"]
tab_alerts, tab_events, tab_signals = st.tabs([f"Alertes ({len(alerts)})", f"Événements des agents ({len(events)})",
                                               f"Signaux corrélés ({len(signals)})"])

# ------------------------------------------------------------------ alertes
with tab_alerts:
    f1, f2 = st.columns(2)
    levels = f1.multiselect("Niveau", ["critical", "warning"], default=["critical", "warning"], format_func=LEVEL_LABELS.get)
    agents = f2.multiselect("Agent à l'origine", list(AGENT_LABELS), default=list(AGENT_LABELS), format_func=AGENT_LABELS.get)
    shown = [a for a in alerts if a["level"] in levels and (not a["agents"] or set(a["agents"]) & set(agents))]
    if not shown:
        st.info("Aucune alerte pour ces filtres.")
    else:
        st.dataframe(pd.DataFrame([{"Nœud": a["node_name"], "Niveau": LEVEL_LABELS[a["level"]], "Risque (%)": round(100 * a["risk"]),
                                    "Direct (%)": round(100 * a["direct"]), "Propagé (%)": round(100 * a["propagated"]),
                                    "Priorité": round(100 * a["priority"]), "Premier signal": a["date"],
                                    "Agents": ", ".join(AGENT_LABELS[x] for x in a["agents"]), "Sources": len(a["source_ids"])}
                                   for a in shown]), hide_index=True, **STRETCH)
        st.caption("Priorité = risque pondéré par la criticité du nœud.")
        pick = st.selectbox("Explication d'une alerte", range(len(shown)), format_func=lambda i: shown[i]["node_name"])
        a = shown[pick]
        st.markdown(f"#### {a['node_name']} {badge(a['level'])}", unsafe_allow_html=True)
        st.markdown(f"**Règle.** {a['rule']}")
        st.markdown("**Chemin dans le graphe.** " + " → ".join(a["path_names"]))
        st.markdown("**Sources.** " + (", ".join(f"`{s}`" for s in a["source_ids"]) or "aucune source directe"))
        by_id = {s["id"]: s for s in signals}
        for sid in a["signal_ids"]:
            s = by_id.get(sid)
            if s:
                st.markdown(f"- {s['node_name']} · {s['family']} · {', '.join(AGENT_LABELS[x] for x in s['agents'])}"
                            f"{' · corroboré par plusieurs agents' if s['corroborated'] else ''} : {s['label']}")

# ------------------------------------------------------------------ événements normalisés
with tab_events:
    f1, f2, f3 = st.columns([2, 2, 3])
    agents_e = f1.multiselect("Agent", list(AGENT_LABELS), default=list(AGENT_LABELS), format_func=AGENT_LABELS.get, key="ev_agents")
    types = sorted({e["event"]["event"]["type"] for e in events})
    types_e = f2.multiselect("Type", types, default=types, key="ev_types")
    text = f3.text_input("Recherche dans le libellé", key="ev_text").strip().lower()
    rows = [e for e in events if e["agent"] in agents_e and e["event"]["event"]["type"] in types_e
            and text in e["event"]["event"]["label"].lower()]
    if not rows:
        st.info("Aucun événement pour ces filtres.")
    else:
        st.dataframe(pd.DataFrame([{
            "Id": e["event"]["event"]["id"], "Agent": AGENT_LABELS[e["agent"]], "Type": e["event"]["event"]["type"],
            "Date": e["event"]["date"], "Lieu": e["event"]["location"]["name"],
            "Nœuds rattachés": ", ".join(e["node_names"]) or "aucun",
            "Rattachement": {"exact": "exact", "elargi": "élargi (0,40)"}.get(e.get("link"), "aucun"),
            "Confiance": e["event"]["meta"]["confidence"], "Sources": len(e["event"]["media"]) or 1,
            "Données manquantes": ", ".join(e["event"]["donnees_manquantes"]), "Libellé": e["event"]["event"]["label"]}
            for e in rows]), hide_index=True, **STRETCH,
            column_config={"Confiance": st.column_config.ProgressColumn("Confiance", min_value=0, max_value=1, format="%.2f")})
        st.caption("Rattachement élargi : l'article ne cite aucun site de la chaîne ; il est relié aux nœuds par une matière "
                   "première, un mot-clé sectoriel ou un pays, et pèse 0,40 fois un rattachement exact (mode live, sans LLM).")
        st.caption("Confiance = confiance de qualification de l'agent (probabilité du classifieur, ou valeur conventionnelle "
                   "pour les mots-clés, le LLM et les seuils). Ce n'est pas un score de gravité.")
        pick = st.selectbox("JSON normalisé d'un événement", range(len(rows)),
                            format_func=lambda i: f"{rows[i]['event']['event']['id']} · {rows[i]['event']['event']['label'][:80]}")
        e = rows[pick]
        left, right = st.columns([3, 2])
        with left:
            st.json(e["event"], expanded=2)
        with right:
            st.metric("Confiance de qualification", f"{e['event']['meta']['confidence']:.2f}")
            st.markdown(f"**Extracteur.** {e['event']['meta']['extractor']} ({e['event']['meta']['detail']})")
            if e.get("extraction"):
                st.markdown(f"**Journal d'extraction.** {e['extraction']['extracteur']} : {e['extraction']['detail']}")
            st.markdown("**Nœuds rattachés.** " + (", ".join(e["node_names"]) or "aucun (signal faible, hors graphe)"))
            for m in e["event"]["media"]:
                st.markdown(f"- `{m['source_id']}` · {m['date'] or 'sans date'} · {m['titre']}")

# ------------------------------------------------------------------ signaux corrélés
with tab_signals:
    if not signals:
        st.info("Aucun signal rattaché au graphe.")
    else:
        only = st.checkbox("Seulement les signaux corroborés par plusieurs agents")
        st.dataframe(pd.DataFrame([{
            "Nœud": s["node_name"], "Famille": s["family"], "Types": ", ".join(s["types"]),
            "Agents": ", ".join(AGENT_LABELS[x] for x in s["agents"]), "Corroboré": "oui" if s["corroborated"] else "non",
            "Rattachement": "élargi" if s.get("link") == "elargi" else "exact",
            "Événements": len(s["event_ids"]), "Sources": len(s["source_ids"]), "Gravité": s["severity"],
            "Confiance": s["confidence"], "Contribution": s["contribution"], "Du": s["first_date"], "Au": s["last_date"]}
            for s in signals if s["corroborated"] or not only]), hide_index=True, **STRETCH)
        st.caption("Un signal regroupe les événements d'une même famille d'aléa sur un même nœud, à moins de 3 jours d'écart. "
                   "Contribution = gravité x confiance x fraîcheur ; c'est elle qui alimente le risque direct du nœud.")
