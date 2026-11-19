// Parcours du graphe côté client : aval d'un nœud (propagation d'une panne), produits finis menacés, alternatives.
import type { GraphEdge, NodeState } from "./types";

/** Nœuds atteints en aval d'un nœud par les liens actifs (les liens de secours ne propagent pas). */
export function downstream(edges: GraphEdge[], from: string): Set<string> {
  const out = new Map<string, string[]>();
  for (const e of edges) if (!e.backup) out.set(e.source, [...(out.get(e.source) ?? []), e.target]);
  const seen = new Set<string>([from]);
  const queue = [from];
  while (queue.length) {
    const cur = queue.shift()!;
    for (const next of out.get(cur) ?? []) if (!seen.has(next)) seen.add(next), queue.push(next);
  }
  return seen;
}

/** Clés `source>target` des liens actifs entre nœuds de l'aval : le chemin de propagation à illuminer. */
export function propagationEdges(edges: GraphEdge[], from: string | null): Set<string> {
  if (!from) return new Set();
  const reach = downstream(edges, from);
  return new Set(edges.filter((e) => !e.backup && reach.has(e.source) && reach.has(e.target)).map((e) => `${e.source}>${e.target}`));
}

export function productsDownstream(nodes: NodeState[], edges: GraphEdge[], from: string): NodeState[] {
  const reach = downstream(edges, from);
  return nodes.filter((n) => n.type === "produit_fini" && reach.has(n.id) && n.id !== from);
}

/** Sources de secours capables de remplacer un nœud auprès de ses clients directs. */
export function alternativesFor(nodes: NodeState[], edges: GraphEdge[], id: string): NodeState[] {
  const clients = new Set(edges.filter((e) => e.source === id && !e.backup).map((e) => e.target));
  const alt = new Set(edges.filter((e) => e.backup && clients.has(e.target) && e.source !== id).map((e) => e.source));
  return nodes.filter((n) => alt.has(n.id));
}
