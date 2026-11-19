"""Copilot Supply Chain : assistant conversationnel avec appel d'outils sur le graphe.

Deux modes, même jeu d'outils :
  - LLM local (Ollama `qwen2.5:7b` ou serveur compatible OpenAI) : le modèle choisit les outils, lit leurs
    résultats et rédige la réponse ;
  - repli déterministe : un routeur d'intentions par règles choisit l'outil, des gabarits rédigent la réponse.
L'assistant ne répond qu'à partir des résultats d'outils. Si le LLM répond sans avoir appelé d'outil, ou s'il
tombe en panne, la réponse déterministe prend le relais : aucun chiffre n'est inventé.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Optional

from src.config import settings
from src.graph.ontology_engine import OntologyEngine
from src.schemas.events import ChatRequest, ChatResponse, ToolCall
from src.utils.llm import LLMError, chat_with_tools, llm_available
from src.utils.text import norm_key

LEVEL_FR = {"ok": "normal", "info": "à surveiller", "warning": "alerte", "critical": "critique"}
MAX_TOOL_ROUNDS = 4

SYSTEM_PROMPT = """Tu es le Copilot d'un outil d'alerte précoce sur les risques de chaîne d'approvisionnement.
Tu aides des acheteurs et des responsables risques. Tu réponds en français, de façon courte et concrète.

RÈGLES
1. Tu ne connais l'état de la chaîne que par les outils. Appelle toujours au moins un outil avant de répondre.
2. N'invente aucun chiffre, aucun fournisseur, aucun événement. Si un outil renvoie une erreur, dis-le.
3. Cite les sources (source_id) et le chemin dans le graphe quand tu expliques une alerte.
4. Pour une question « que se passe-t-il si... », appelle simuler_perturbation. La gravité va de 0 à 1
   (« bloqué à 80 % » = 0.8, « fermeture » = 1.0). Une simulation ne modifie pas l'état réel : précise-le.
5. Pour un plan de contournement, appelle plan_mitigation et présente les actions par ordre de délai.
6. Si le nœud demandé est ambigu ou inconnu, demande une précision plutôt que de deviner."""


def _tool(name: str, description: str, properties: Optional[dict] = None, required: Optional[list] = None) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties or {}, "required": required or []}}}


_NODE = {"type": "string", "description": "Nom ou identifiant du nœud (ex. « port de Kaohsiung », « Formoz », sup_chip_tw)"}
TOOL_SPECS = [
    _tool("etat_global", "Indice de risque global, nombre d'alertes, nœuds critiques, date et mode de l'état courant."),
    _tool("noeuds_exposes", "Nœuds les plus exposés au risque, du plus au moins exposé.",
          {"n": {"type": "integer", "description": "nombre de nœuds", "default": 5}}),
    _tool("produits_menaces", "Produits finis menacés, avec leur risque et le chemin qui l'explique."),
    _tool("expliquer_alertes", "Alertes actives avec règle déclenchée, chemin dans le graphe, agents et source_id.",
          {"noeud": dict(_NODE, description="filtre optionnel sur un nœud"), "n": {"type": "integer", "default": 5}}),
    _tool("chemin_critique", "Chemin de risque actuel d'un nœud et nœuds amont dont il dépend le plus.", {"noeud": _NODE}, ["noeud"]),
    _tool("fournisseurs_alternatifs", "Sources alternatives pour les clients d'un nœud (réserve, secours, délai).", {"noeud": _NODE}, ["noeud"]),
    _tool("simuler_perturbation", "Simulation what-if d'une panne sur un nœud, sans modifier l'état réel.",
          {"noeud": _NODE, "gravite": {"type": "number", "description": "0 à 1 (0.8 = bloqué à 80 %)"}}, ["noeud", "gravite"]),
    _tool("plan_mitigation", "Plan de contournement pour un nœud : réallocations, routes de secours, stocks.", {"noeud": _NODE}, ["noeud"]),
]


class CopilotAssistant:
    def __init__(self, engine: OntologyEngine, chat_fn: Callable = chat_with_tools, available_fn: Callable = llm_available):
        self.engine = engine
        self._chat_fn, self._available_fn = chat_fn, available_fn
        self.tools: dict[str, Callable[..., dict]] = {
            "etat_global": self.etat_global, "noeuds_exposes": self.noeuds_exposes,
            "produits_menaces": self.produits_menaces, "expliquer_alertes": self.expliquer_alertes,
            "chemin_critique": self.chemin_critique, "fournisseurs_alternatifs": self.fournisseurs_alternatifs,
            "simuler_perturbation": self.simuler_perturbation, "plan_mitigation": self.plan_mitigation}

    # ------------------------------------------------------------------ outils (résultats sérialisables en JSON)
    def _resolve(self, noeud: Any) -> tuple[Optional[str], Optional[dict]]:
        nid = str(noeud) if str(noeud) in self.engine.nodes else self.engine.resolve_node(str(noeud or ""))
        if nid is None:
            return None, {"erreur": f"nœud inconnu : « {noeud} »",
                          "exemples": [n.name for n in self.engine.nodes.values() if n.type in ("port", "fournisseur")][:8]}
        return nid, None

    def etat_global(self) -> dict:
        st, alerts = self.engine.state(), self.engine.alerts()
        agents: dict[str, int] = {}
        for s in self.engine.current.signals:
            for a in s.agents:
                agents[a] = agents.get(a, 0) + 1
        return {"date": st.as_of, "mode": st.mode, "indice_risque_global": st.global_risk_index,
                "evenements": len(self.engine.events), "alertes": len(alerts),
                "noeuds_critiques": self.engine.names(st.critical_nodes), "signaux_par_agent": agents,
                "vide": not self.engine.events}

    def noeuds_exposes(self, n: int = 5) -> dict:
        rows = [{"id": s.id, "nom": s.name, "type": s.type, "risque": s.risk, "niveau": s.level, "direct": s.direct,
                 "propage": s.propagated, "chemin": self.engine.names(s.path)}
                for s in self.engine.top_exposed(max(1, min(int(n or 5), 15))) if s.risk > 0]
        return {"noeuds": rows}

    def produits_menaces(self) -> dict:
        rows = [{"id": s.id, "nom": s.name, "risque": s.risk, "niveau": s.level, "chemin": self.engine.names(s.path)}
                for s in self.engine.threatened_products()]
        return {"date": self.engine.current.as_of, "produits": rows}

    def expliquer_alertes(self, noeud: Optional[str] = None, n: int = 5) -> dict:
        alerts = self.engine.alerts()
        if noeud:
            nid, err = self._resolve(noeud)
            if err:
                return err
            own = [a for a in alerts if a.node_id == nid]
            alerts = own or [a for a in alerts if nid in a.path]     # pas d'alerte sur ce nœud : celles qui passent par lui
        rows = [{"noeud": a.node_name, "niveau": a.level, "risque": a.risk, "regle": a.rule, "chemin": a.path_names,
                 "agents": a.agents, "source_id": a.source_ids[:6], "resume": a.summary, "date_premier_signal": a.date}
                for a in alerts[:max(1, min(int(n or 5), 15))]]
        return {"total": len(alerts), "alertes": rows}

    def chemin_critique(self, noeud: str) -> dict:
        nid, err = self._resolve(noeud)
        if err:
            return err
        r = self.engine.current.risks[nid]
        return {"noeud_id": nid, "noeud": self.engine.nodes[nid].name, "risque": r["risk"],
                "chemin_de_risque_actuel": self.engine.names(r["path"]),
                "dependances_amont": [{"nom": d["name"], "type": d["type"], "risque_si_panne_totale": d["risk_if_down"]}
                                      for d in self.engine.dependency_ranking(nid)],
                "produits_en_aval": self.engine.names(self.engine.downstream_products(nid))}

    def fournisseurs_alternatifs(self, noeud: str) -> dict:
        nid, err = self._resolve(noeud)
        if err:
            return err
        return {"noeud_id": nid, "noeud": self.engine.nodes[nid].name, "clients": self.engine.alternative_suppliers(nid)}

    def simuler_perturbation(self, noeud: str, gravite: float = 0.8) -> dict:
        nid, err = self._resolve(noeud)
        if err:
            return err
        try:
            severity = float(gravite)
        except (TypeError, ValueError):
            return {"erreur": f"gravité illisible : {gravite!r} (attendu : nombre entre 0 et 1)"}
        if severity > 1:                                 # « 80 » compris comme 80 %
            severity /= 100
        severity = max(0.0, min(1.0, severity))
        sim = self.engine.simulate_disruption(nid, severity)
        return {"noeud_id": nid, "noeud": sim.node_name, "gravite": severity, "etat_reel_modifie": False,
                "indice_avant": sim.baseline_index, "indice_apres": sim.simulated_index,
                "impacts": [{"nom": i.name, "type": i.type, "avant": i.baseline, "apres": i.simulated, "niveau": i.level,
                             "chemin": self.engine.names(i.path)} for i in sim.impacts[:8]],
                "produits_menaces": [{"nom": p.name, "avant": p.baseline, "apres": p.simulated, "niveau": p.level}
                                     for p in sim.threatened_products]}

    def plan_mitigation(self, noeud: str) -> dict:
        nid, err = self._resolve(noeud)
        if err:
            return err
        plan = self.engine.mitigation_plan(nid)
        return {"noeud_id": nid, "noeud": plan.node_name, "produits_en_aval": plan.threatened_products,
                "couverture_par_client": plan.coverage,
                "actions": [{"type": a.kind, "cible": a.target, "action": a.description, "delai_jours": a.lead_time_days}
                            for a in plan.actions]}

    def run_tool(self, name: str, arguments: dict) -> dict:
        """Exécute un outil. Ne lève jamais d'exception : une erreur revient dans le résultat."""
        fn = self.tools.get(name)
        if fn is None:
            return {"erreur": f"outil inconnu : {name}"}
        try:
            return fn(**{k: v for k, v in (arguments or {}).items() if v is not None})
        except TypeError as e:
            return {"erreur": f"arguments invalides pour {name} : {e}"}
        except Exception as e:
            return {"erreur": f"{type(e).__name__} : {e}"}

    # ------------------------------------------------------------------ point d'entrée
    def chat(self, req: ChatRequest, use_llm: Optional[bool] = None) -> ChatResponse:
        use_llm = settings.use_llm if use_llm is None else use_llm
        note = ""
        if use_llm:
            if self._available_fn():
                try:
                    return self._chat_llm(req)
                except LLMError as e:
                    note = f"LLM indisponible ({e}) : réponse déterministe."
            else:
                note = f"Serveur LLM injoignable à {settings.llm_base_url} : réponse déterministe."
        return self._chat_rules(req, note)

    # ------------------------------------------------------------------ mode LLM
    def _chat_llm(self, req: ChatRequest) -> ChatResponse:
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages += [{"role": t.role, "content": t.content} for t in req.history[-6:]]
        messages.append({"role": "user", "content": req.message})
        calls: list[ToolCall] = []
        context = dict(req.context)
        for _ in range(MAX_TOOL_ROUNDS):
            out = self._chat_fn(messages, TOOL_SPECS)
            if not out["tool_calls"]:
                if not calls:
                    raise LLMError("le modèle a répondu sans consulter le graphe")
                if not out["content"].strip():
                    raise LLMError("réponse vide du modèle")
                return ChatResponse(answer=out["content"].strip(), mode="llm", tool_calls=calls, context=context)
            messages.append(out.get("raw") or {"role": "assistant", "content": out["content"]})
            for call in out["tool_calls"]:
                result = self.run_tool(call["name"], call["arguments"])
                calls.append(ToolCall(name=call["name"], arguments=call["arguments"], result=result))
                if result.get("noeud_id"):
                    context["last_node_id"] = result["noeud_id"]
                tool_msg = {"role": "tool", "tool_name": call["name"], "content": json.dumps(result, ensure_ascii=False)}
                if call.get("id"):
                    tool_msg["tool_call_id"] = call["id"]            # format OpenAI
                messages.append(tool_msg)
        raise LLMError(f"pas de réponse finale après {MAX_TOOL_ROUNDS} séries d'appels d'outils")

    # ------------------------------------------------------------------ mode déterministe
    @staticmethod
    def parse_severity(text: str) -> float:
        """« à 80 % » -> 0,8 ; fermeture ou arrêt complet -> 1,0 ; blocage sans chiffre -> 0,8 ; sinon 0,7."""
        m = re.search(r"(\d{1,3})\s*(?:%|pour ?cent|percent)", text)
        if m:
            return max(0.0, min(1.0, int(m.group(1)) / 100))
        t = norm_key(text)
        if re.search(r"fermeture|ferme|closure|closed|shutdown|totale?|complet|a l'arret|faillite", t):
            return 1.0
        if re.search(r"bloqu|block|greve|strike", t):
            return 0.8
        return 0.7

    def route(self, message: str, context: dict) -> tuple[str, dict]:
        """Choisit l'outil et ses arguments à partir de la phrase. Renvoie (outil, arguments)."""
        t = norm_key(message)
        nid = self.engine.resolve_node(message)
        fallback = nid or context.get("last_node_id")
        if fallback not in self.engine.nodes:
            fallback = None
        has = lambda pattern: bool(re.search(pattern, t))

        if has(r"simul|que se passe|qu'arrive|what if|what happens|et si\b|imagin|hypoth"):
            return ("simuler_perturbation", {"noeud": nid, "gravite": self.parse_severity(message)}) if nid \
                else ("_demander_noeud", {"action": "simuler une perturbation"})
        if has(r"plan|contourn|mitig|que faire|quoi faire|solution|recommand|workaround"):
            target = fallback or self._most_exposed_source()
            return ("plan_mitigation", {"noeud": target}) if target else ("etat_global", {})
        if has(r"alternati|second source|seconde source|remplac|substitu|autre fournisseur|backup|secours"):
            return ("fournisseurs_alternatifs", {"noeud": fallback}) if fallback \
                else ("_demander_noeud", {"action": "chercher des fournisseurs alternatifs"})
        if nid and has(r"bloqu|ferm|panne|arret|greve|closure|strike|down"):
            return "simuler_perturbation", {"noeud": nid, "gravite": self.parse_severity(message)}
        if has(r"produits? finis?|menac|threat|finished product"):
            return "produits_menaces", {}
        if has(r"chemin|path|depend|amont|upstream|defaillance"):
            return ("chemin_critique", {"noeud": fallback}) if fallback \
                else ("_demander_noeud", {"action": "calculer un chemin critique"})
        if has(r"alerte|alert|pourquoi|why|expliqu|explain|resum|summar|source|preuve"):
            return "expliquer_alertes", ({"noeud": nid} if nid else {})
        if has(r"expos|risqu|critique|critical|top|pire|worst|vulnerab"):
            return "noeuds_exposes", {}
        if nid:
            return "chemin_critique", {"noeud": nid}
        return "etat_global", {}

    def _most_exposed_source(self) -> Optional[str]:
        """Origine du risque la plus forte : premier nœud du chemin de l'alerte la plus prioritaire."""
        alerts = self.engine.alerts()
        return alerts[0].path[0] if alerts else None

    def _chat_rules(self, req: ChatRequest, note: str = "") -> ChatResponse:
        context = dict(req.context)
        name, args = self.route(req.message, context)
        if name == "_demander_noeud":
            examples = ", ".join(n.name for n in self.engine.nodes.values() if n.type == "port")
            return ChatResponse(answer=f"Sur quel nœud dois-je {args['action']} ? Par exemple : {examples}.",
                                mode="deterministic", context=context, note=note)
        result = self.run_tool(name, args)
        if result.get("noeud_id"):
            context["last_node_id"] = result["noeud_id"]
        answer = self.render(name, result)
        return ChatResponse(answer=answer, mode="deterministic", context=context, note=note,
                            tool_calls=[ToolCall(name=name, arguments=args, result=result)])

    # ------------------------------------------------------------------ gabarits de réponse
    def render(self, name: str, r: dict) -> str:
        if "erreur" in r:
            extra = f" Exemples : {', '.join(r['exemples'])}." if r.get("exemples") else ""
            return f"Je ne peux pas répondre : {r['erreur']}.{extra}"
        return getattr(self, f"_render_{name}")(r)

    @staticmethod
    def _pct(x: float) -> str:
        return f"{100 * x:.0f} %"

    def _render_etat_global(self, r: dict) -> str:
        if r["vide"]:
            return ("Aucune donnée chargée : lancez d'abord le pipeline (mode Replay ou Live) depuis la Tour de contrôle.\n\n"
                    "Je peux ensuite : lister les produits menacés, expliquer une alerte, simuler une panne "
                    "(« que se passe-t-il si le port de Kaohsiung est bloqué à 80 % ? ») et proposer un plan de contournement.")
        crit = ", ".join(r["noeuds_critiques"]) or "aucun"
        agents = ", ".join(f"{a} : {n}" for a, n in sorted(r["signaux_par_agent"].items())) or "aucun"
        return (f"**État au {r['date']} (mode {r['mode']})**\n\n- Indice de risque global : **{r['indice_risque_global']} / 100**\n"
                f"- Alertes actives : {r['alertes']} ({r['evenements']} événements)\n- Nœuds critiques : {crit}\n"
                f"- Signaux par agent : {agents}\n\n"
                "Vous pouvez me demander les produits menacés, l'explication d'une alerte, une simulation ou un plan de contournement.")

    def _render_noeuds_exposes(self, r: dict) -> str:
        if not r["noeuds"]:
            return "Aucun nœud n'est exposé pour l'instant : aucun signal n'a été rattaché au graphe."
        lines = [f"{i}. **{n['nom']}** ({n['type']}) : {self._pct(n['risque'])}, {LEVEL_FR[n['niveau']]} "
                 f"(direct {self._pct(n['direct'])}, propagé {self._pct(n['propage'])})"
                 for i, n in enumerate(r["noeuds"], start=1)]
        return "**Nœuds les plus exposés**\n\n" + "\n".join(lines)

    def _render_produits_menaces(self, r: dict) -> str:
        if not r["produits"]:
            return f"Au {r['date'] or 'dernier calcul'}, aucun produit fini ne dépasse le seuil de surveillance (15 %)."
        lines = [f"- **{p['nom']}** : {self._pct(p['risque'])} ({LEVEL_FR[p['niveau']]}). Chemin : {' → '.join(p['chemin'])}"
                 for p in r["produits"]]
        return f"**Produits finis menacés au {r['date']}**\n\n" + "\n".join(lines)

    def _render_expliquer_alertes(self, r: dict) -> str:
        if not r["alertes"]:
            return "Aucune alerte active sur ce périmètre."
        blocks = []
        for a in r["alertes"]:
            src = ", ".join(f"`{s}`" for s in a["source_id"]) or "aucune source directe"
            blocks.append(f"**{a['noeud']}** : {self._pct(a['risque'])} ({LEVEL_FR[a['niveau']]})\n"
                          f"- Règle : {a['regle']}\n- Chemin : {' → '.join(a['chemin'])}\n"
                          f"- Agents : {', '.join(a['agents']) or 'aucun'} · Sources : {src}")
        more = f"\n\n{r['total'] - len(r['alertes'])} autre(s) alerte(s) non affichée(s)." if r["total"] > len(r["alertes"]) else ""
        return f"**{r['total']} alerte(s) active(s)**\n\n" + "\n\n".join(blocks) + more

    def _render_chemin_critique(self, r: dict) -> str:
        deps = "\n".join(f"- {d['nom']} ({d['type']}) : risque de {self._pct(d['risque_si_panne_totale'])} s'il tombe en panne totale"
                         for d in r["dependances_amont"]) or "- aucune dépendance amont"
        prods = ", ".join(r["produits_en_aval"]) or "aucun"
        return (f"**{r['noeud']}** : risque actuel {self._pct(r['risque'])}\n\n"
                f"Chemin de risque actuel : {' → '.join(r['chemin_de_risque_actuel'])}\n\n"
                f"Dépendances amont les plus sensibles :\n{deps}\n\nProduits finis en aval : {prods}")

    def _render_fournisseurs_alternatifs(self, r: dict) -> str:
        if not r["clients"]:
            return f"**{r['noeud']}** n'a aucun client en aval dans le graphe."
        blocks = []
        for c in r["clients"]:
            alts = "\n".join(f"  - {a['name']} ({a['kind']}) : réserve {self._pct(a['spare_capacity'])}, délai {a['lead_time_days']:.0f} j, "
                             f"risque actuel {self._pct(a['risk'])}" for a in c["alternatives"]) or "  - aucune alternative : source unique"
            blocks.append(f"- **{c['customer']}** ({c['input']}, part exposée {self._pct(c['share_at_risk'])}, "
                          f"couverture possible {self._pct(c['coverage'])})\n{alts}")
        return f"**Alternatives à {r['noeud']}**\n\n" + "\n".join(blocks)

    def _render_simuler_perturbation(self, r: dict) -> str:
        if not r["impacts"]:
            return (f"Simulation : **{r['noeud']}** perturbé à {self._pct(r['gravite'])}. Aucun impact supplémentaire : "
                    "le nœud est déjà au moins aussi dégradé dans l'état réel.")
        lines = [f"- {i['nom']} ({i['type']}) : {self._pct(i['avant'])} → **{self._pct(i['apres'])}** ({LEVEL_FR[i['niveau']]})"
                 for i in r["impacts"]]
        prods = ", ".join(f"{p['nom']} ({self._pct(p['apres'])})" for p in r["produits_menaces"]) or "aucun au-dessus du seuil de surveillance"
        return (f"**Simulation : {r['noeud']} perturbé à {self._pct(r['gravite'])}** (l'état réel n'est pas modifié)\n\n"
                f"Indice de risque global : {r['indice_avant']} → **{r['indice_apres']} / 100**\n\n"
                f"Onde de choc :\n" + "\n".join(lines) + f"\n\nProduits finis menacés : {prods}\n\n"
                "Demandez « propose un plan de contournement » pour les actions possibles.")

    def _render_plan_mitigation(self, r: dict) -> str:
        titles = {"reallocation": "Réallouer", "route_secours": "Route de secours", "stock": "Stocks", "surveillance": "Surveillance"}
        lines = [f"{i}. **{titles[a['type']]}** : {a['action']}" for i, a in enumerate(r["actions"], start=1)]
        cov = "\n".join(f"- {k} : {self._pct(v)} du besoin récupérable" for k, v in r["couverture_par_client"].items())
        prods = ", ".join(r["produits_en_aval"]) or "aucun"
        return (f"**Plan de contournement pour {r['noeud']}**\n\nProduits finis en aval : {prods}\n\n" + "\n".join(lines) +
                (f"\n\nCouverture par client :\n{cov}" if cov else "") +
                "\n\nLes capacités et délais viennent de la topologie (données simulées) : à confirmer avec les fournisseurs.")
