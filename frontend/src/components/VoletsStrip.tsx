// Bandeau du tableau de bord : résumé des volets Météo et Finance et familles d'aléa actives sur la chaîne.
import { ArrowRight, Banknote, CloudSun, Layers } from "lucide-react";
import { useMemo } from "react";
import { dataApi } from "../api_data";
import { useStore } from "../store";
import { frDate } from "../theme";
import { FAMILY_STYLE, FamilyChip, pct0, signed, useAsync } from "./viz";

export default function VoletsStrip() {
  const { setView, events, run } = useStore();
  const wx = useAsync(() => dataApi.weather(), [run?.as_of]);
  const fin = useAsync(() => dataApi.finance(), [run?.as_of]);
  const families = useMemo(() => {
    const c = new Map<string, number>();
    for (const s of events?.signals ?? []) c.set(s.family, (c.get(s.family) ?? 0) + s.contribution);
    return [...c.entries()].sort((a, b) => b[1] - a[1]);
  }, [events]);
  const next = wx.data?.forecast?.[0];
  const nextSite = next ? wx.data?.sites.find((s) => s.site === next.site) : null;
  const finAlerts = (fin.data?.signals ?? []).filter((s) => s.en_alerte).slice(0, 3);

  return (
    <div className="grid gap-4 md:grid-cols-3">
      <button onClick={() => setView("weather")} className="card group p-4 text-left transition hover:border-slate-300 hover:shadow-soft">
        <div className="label flex items-center gap-1.5"><CloudSun size={13} /> Volet météo</div>
        {!wx.data?.ready ? (
          <div className="mt-2 text-sm text-ink-mute">Base météo vide.</div>
        ) : (
          <>
            <div className="mt-2 text-sm">
              <b className="tnum text-lg">{wx.data.kpis.forecast_alerts}</b> alerte(s) prévue(s) sur 16 jours ·{" "}
              <span className="text-ink-mute">{wx.data.kpis.hubs_calibrated}/{wx.data.kpis.hubs_watched} hubs calibrés</span>
            </div>
            <div className="mt-1 truncate text-[12px] text-ink-soft">
              {next ? `Prochaine : ${wx.data.indicators[next.indicator]?.label ?? next.indicator} à ${nextSite?.name ?? next.site} le ${frDate(next.date)}` : "Aucune alerte prévue."}
            </div>
          </>
        )}
        <div className="mt-2 flex items-center gap-1 text-xs font-semibold text-ink-mute group-hover:text-ink-soft">Ouvrir <ArrowRight size={13} /></div>
      </button>

      <button onClick={() => setView("finance")} className="card group p-4 text-left transition hover:border-slate-300 hover:shadow-soft">
        <div className="label flex items-center gap-1.5"><Banknote size={13} /> Marchés & fournisseurs</div>
        {!fin.data?.ready ? (
          <div className="mt-2 text-sm text-ink-mute">Base finance vide.</div>
        ) : (
          <>
            <div className="mt-2 text-sm">
              <b className="tnum text-lg">{fin.data.kpis.signals_alert}</b> signal(aux) en alerte · score {pct0(fin.data.kpis.score)} ·{" "}
              <span className="text-ink-mute">{fin.data.kpis.suppliers_alert} fournisseur(s) en alerte</span>
            </div>
            <div className="mt-1 truncate text-[12px] text-ink-soft">
              {finAlerts.length ? finAlerts.map((s) => `${s.nom} ${s.mesure === "niveau" ? s.indicateur : `${signed(s.indicateur)} %`}`).join(" · ") : "Aucun signal en alerte."}
            </div>
          </>
        )}
        <div className="mt-2 flex items-center gap-1 text-xs font-semibold text-ink-mute group-hover:text-ink-soft">Ouvrir <ArrowRight size={13} /></div>
      </button>

      <div className="card p-4">
        <div className="label flex items-center gap-1.5"><Layers size={13} /> Familles d'aléa sur la chaîne</div>
        {families.length === 0 ? (
          <div className="mt-2 text-sm text-ink-mute">Aucun signal corrélé.</div>
        ) : (
          <div className="mt-2 space-y-1.5">
            {families.slice(0, 4).map(([f, v]) => (
              <div key={f} className="flex items-center gap-2">
                <FamilyChip family={f} />
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
                  <div className="h-full rounded-full" style={{ width: `${Math.min(100, (v / families[0][1]) * 100)}%`, background: FAMILY_STYLE[f]?.color ?? "#64748b" }} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
