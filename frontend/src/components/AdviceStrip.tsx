// Bandeau de conseil opérationnel, sous la bannière d'état : une ligne, une recommandation, une action rapide.
import { ArrowRight, Lightbulb } from "lucide-react";
import { useMemo } from "react";
import { alternativesFor, productsDownstream } from "../graphUtils";
import { useStore } from "../store";
import { AGENT_STYLE, fmt1, pct } from "../theme";
import type { AgentName } from "../types";

const list = (names: string[], max = 2) => (names.length <= max ? names.join(" et ") : `${names.slice(0, max).join(", ")} et ${names.length - max} autre(s)`);

/** Recommandation : celle du backend si l'API en fournit une, sinon règles déterministes sur le score global,
 *  le nœud le plus exposé et la source dominante des signaux. */
function useAdvice() {
  const { run, state, events } = useStore();
  return useMemo(() => {
    if (!run || !state) return null;
    const top = [...state.nodes].sort((a, b) => b.risk - a.risk)[0];
    if (!top) return null;
    if (run.recommendation) return { text: run.recommendation, node: top };

    const idx = state.global_risk_index;
    const weight: Record<AgentName, number> = { media: 0, finance: 0, weather: 0 };
    for (const s of events?.signals ?? []) for (const a of s.agents) weight[a] += s.contribution;
    const dominant = (Object.keys(weight) as AgentName[]).sort((a, b) => weight[b] - weight[a])[0];
    const hasSignals = weight[dominant] > 0;
    const exposed = `${top.name} (${pct(top.risk)})`;

    if (idx < 20) {
      return {
        node: top,
        text: top.risk >= 0.01
          ? `Chaîne fluide — maintenir une veille passive sur ${exposed} et tester sa résilience dans le simulateur What-If.`
          : "Chaîne fluide — aucun maillon exposé ; tester la résilience des nœuds les plus critiques dans le simulateur What-If.",
      };
    }
    if (idx <= 50) {
      const alts = alternativesFor(state.nodes, state.edges, top.id).map((n) => n.name);
      const source = hasSignals ? `signaux ${AGENT_STYLE[dominant].label} dominants` : "signaux modérés";
      return {
        node: top,
        text: `Vigilance (${fmt1(idx)}/100), ${source} — ${exposed} est le maillon le plus exposé : ${
          alts.length ? `vérifier la capacité des alternatives (${list(alts)})` : "identifier et qualifier des sources alternatives"
        }.`,
      };
    }
    const products = productsDownstream(state.nodes, state.edges, top.id).map((n) => n.name);
    return {
      node: top,
      text: `Action prioritaire — sécuriser ${exposed}${hasSignals ? ` (signaux ${AGENT_STYLE[dominant].label})` : ""} et protéger ${
        products.length ? `les produits finis en aval : ${list(products)}` : "les produits finis en aval"
      } (stocks, routes de secours).`,
    };
  }, [run, state, events]);
}

export default function AdviceStrip() {
  const advice = useAdvice();
  const { setWhatIfNode, setView } = useStore();
  if (!advice) return null;
  return (
    <div className="flex items-center gap-3 rounded-xl border border-line bg-white px-4 py-2.5 text-sm shadow-sm">
      <Lightbulb size={15} className="shrink-0 text-ink-mute" aria-hidden />
      <p className="min-w-0 flex-1 truncate text-ink-soft" title={advice.text}>
        <span className="font-semibold text-ink">Conseil :</span> {advice.text}
      </p>
      <button
        onClick={() => {
          setWhatIfNode(advice.node.id);
          setView("chain");
          window.scrollTo({ top: 0 });
        }}
        className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap text-xs font-semibold text-sky-700 hover:underline"
      >
        Simuler ce nœud <ArrowRight size={13} />
      </button>
    </div>
  );
}
