// Tableau synthétique : stocks de sécurité, risque direct vs propagé, chemin critique.
import { ArrowDownUp } from "lucide-react";
import { useMemo, useState } from "react";
import { LEVEL_STYLE, TYPE_LABEL, pct } from "../theme";
import type { NodeState } from "../types";
import { LevelBadge, SoftBar } from "./ui";

type SortKey = "risk" | "direct" | "propagated" | "stock_days" | "name";

export default function ChainTable({ nodes, onOpen }: { nodes: NodeState[]; onOpen: (id: string) => void }) {
  const [sort, setSort] = useState<SortKey>("risk");
  const byId = new Map(nodes.map((n) => [n.id, n.name]));
  const rows = useMemo(
    () => [...nodes].sort((a, b) => (sort === "name" ? a.name.localeCompare(b.name) : sort === "stock_days" ? a.stock_days - b.stock_days : b[sort] - a[sort])),
    [nodes, sort],
  );
  const Th = ({ k, children, className = "" }: { k?: SortKey; children: React.ReactNode; className?: string }) => (
    <th className={`label whitespace-nowrap px-3 py-2.5 text-left ${className}`}>
      {k ? (
        <button onClick={() => setSort(k)} className={`inline-flex items-center gap-1 ${sort === k ? "text-ink" : ""}`}>
          {children} <ArrowDownUp size={11} />
        </button>
      ) : (
        children
      )}
    </th>
  );
  return (
    <div className="overflow-x-auto scroll-thin rounded-xl ring-1 ring-line">
      <table className="w-full min-w-[860px] text-sm">
        <thead className="bg-slate-50/80">
          <tr>
            <Th k="name">Nœud</Th>
            <Th>Type · lieu</Th>
            <Th k="stock_days" className="text-right">Stock</Th>
            <Th k="direct">Direct</Th>
            <Th k="propagated">Propagé</Th>
            <Th k="risk">Total</Th>
            <Th>Niveau</Th>
            <Th>Chemin critique</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((n) => (
            <tr key={n.id} onClick={() => onOpen(n.id)} className="cursor-pointer border-t border-line/70 transition hover:bg-slate-50/70">
              <td className="px-3 py-2.5 font-semibold text-ink">{n.name}</td>
              <td className="px-3 py-2.5 text-xs text-ink-mute">
                {TYPE_LABEL[n.type]}
                {n.place ? ` · ${n.place}` : ""}
              </td>
              <td className="tnum px-3 py-2.5 text-right">
                <span className={n.stock_days > 0 && n.stock_days < 10 ? "font-semibold text-amber-700" : "text-ink-soft"}>{n.stock_days ? `${n.stock_days} j` : "—"}</span>
              </td>
              <td className="tnum px-3 py-2.5 text-ink-soft">{pct(n.direct)}</td>
              <td className="tnum px-3 py-2.5 text-ink-soft">{pct(n.propagated)}</td>
              <td className="px-3 py-2.5">
                <div className="flex w-32 items-center gap-2">
                  <SoftBar value={n.risk} level={n.level} height={5} />
                  <span className="tnum w-9 text-right text-xs font-bold" style={{ color: LEVEL_STYLE[n.level].color }}>
                    {pct(n.risk)}
                  </span>
                </div>
              </td>
              <td className="px-3 py-2.5">
                <LevelBadge level={n.level} size="xs" />
              </td>
              <td className="max-w-[280px] truncate px-3 py-2.5 text-xs text-ink-mute" title={n.path.map((id) => byId.get(id) ?? id).join(" → ")}>
                {n.path.length > 1 ? n.path.map((id) => byId.get(id) ?? id).join(" → ") : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
