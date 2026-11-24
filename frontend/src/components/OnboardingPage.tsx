// Page « Nouveau client » : inscription en quatre étapes (entreprise, chaîne, interlocuteur, validation).
// Données personnelles réduites au contact professionnel, stockées à part de la chaîne (voir src/onboarding.py).
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowLeft, ArrowRight, Building2, Check, CheckCircle2, Download, EyeOff, Factory, Loader2, Network, Plus,
  ShieldCheck, Trash2, UserRound, type LucideIcon,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { API_URL, api } from "../api";
import type { Gabarit, Inscription, InscriptionResultat } from "../types";
import { useStore } from "../store";
import { Card } from "./ui";

// Adresse de contact pour l'exercice des droits : à remplacer par l'adresse réelle avant toute mise en service.
const CONTACT_RGPD = "dpo@aegis.example";
const SECTEURS = ["Pharmacie", "Automobile", "Aéronautique", "Électronique", "Chimie", "Agroalimentaire", "Distribution", "Énergie", "Autre"];
const TAILLES = ["TPE", "PME", "ETI", "Grande entreprise"] as const;

type Site = { nom: string; ville: string; pays: string; stock_jours: number };
type Point = { nom: string; ville: string; pays: string; type: "port" | "hub" };
type Fournisseur = { nom: string; ville: string; pays: string; categorie: string; site: string; part_pct: number; passage: string; stock_jours: number; critique: boolean };
type Produit = { nom: string; site: string };

const STEPS: { label: string; icon: LucideIcon }[] = [
  { label: "Entreprise", icon: Building2 },
  { label: "Chaîne d'approvisionnement", icon: Network },
  { label: "Interlocuteur", icon: UserRound },
  { label: "Validation", icon: ShieldCheck },
];

const vide = { site: (): Site => ({ nom: "", ville: "", pays: "", stock_jours: 15 }),
  point: (): Point => ({ nom: "", ville: "", pays: "", type: "port" }),
  fournisseur: (site = ""): Fournisseur => ({ nom: "", ville: "", pays: "", categorie: "", site, part_pct: 100, passage: "", stock_jours: 15, critique: false }),
  produit: (site = ""): Produit => ({ nom: "", site }) };

const rempli = (...v: (string | undefined)[]) => v.every((x) => (x ?? "").trim().length > 0);

export default function OnboardingPage() {
  const { refreshTopologies, setMode, setTopologyRef, setView } = useStore();
  const [step, setStep] = useState(0);
  const [params, setParams] = useState<{ gabarits: Gabarit[]; version_notice: string; conservation_annees: number } | null>(null);
  const [entreprise, setEntreprise] = useState({ raison_sociale: "", secteur: "", pays: "", taille: "PME" as (typeof TAILLES)[number] });
  const [source, setSource] = useState<"chaine" | "gabarit">("chaine");
  const [gabarit, setGabarit] = useState("");
  const [sites, setSites] = useState<Site[]>([vide.site()]);
  const [points, setPoints] = useState<Point[]>([]);
  const [fournisseurs, setFournisseurs] = useState<Fournisseur[]>([vide.fournisseur()]);
  const [produits, setProduits] = useState<Produit[]>([vide.produit()]);
  const [pseudo, setPseudo] = useState(true);
  const [contact, setContact] = useState({ prenom: "", nom: "", email: "", fonction: "" });
  const [accords, setAccords] = useState({ traitement: false, habilitation: false });
  const [busy, setBusy] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [resultat, setResultat] = useState<InscriptionResultat | null>(null);

  useEffect(() => {
    api.clientParams().then((p) => { setParams(p); setGabarit(p.gabarits[0]?.id ?? ""); }).catch((e) => setErreur((e as Error).message));
  }, []);

  const nomsSites = sites.map((s) => s.nom.trim()).filter(Boolean);
  const valide = [
    rempli(entreprise.raison_sociale, entreprise.secteur, entreprise.pays),
    source === "gabarit" ? !!gabarit
      : sites.every((s) => rempli(s.nom, s.ville, s.pays)) && fournisseurs.every((f) => rempli(f.nom, f.ville, f.pays, f.categorie, f.site))
        && points.every((p) => rempli(p.nom, p.ville, p.pays)) && produits.every((p) => rempli(p.nom, p.site)),
    rempli(contact.prenom, contact.nom) && /^[^@\s]+@[^@\s]+\.[a-z]{2,}$/i.test(contact.email.trim()),
    accords.traitement && accords.habilitation,
  ];

  const corps = (): Inscription => ({
    entreprise,
    contact: { ...contact, fonction: contact.fonction.trim() || null },
    gabarit: source === "gabarit" ? gabarit : null,
    chaine: source === "chaine"
      ? { sites, points_logistiques: points, produits, fournisseurs: fournisseurs.map((f) => ({ ...f, passage: f.passage || null })) }
      : null,
    pseudonymiser_fournisseurs: pseudo,
    consentements: { ...accords, version_notice: params?.version_notice ?? "" },
  });

  const envoyer = async () => {
    setBusy(true);
    setErreur(null);
    try {
      const r = await api.inscription(corps());
      setResultat(r);
      await refreshTopologies();
    } catch (e) {
      setErreur((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (resultat) {
    return (
      <Confirmation
        r={resultat}
        societe={entreprise.raison_sociale}
        onAnalyse={() => { setMode("live"); setTopologyRef(resultat.topology_ref); setView("dashboard"); }}
      />
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <div>
        <h1 className="text-xl font-extrabold tracking-tight">Nouveau client</h1>
        <p className="text-sm text-ink-mute">Créez l'espace de surveillance d'une entreprise en quelques minutes. Seules les informations utiles au service sont demandées.</p>
      </div>

      <ol className="grid grid-cols-4 gap-2">
        {STEPS.map((s, i) => {
          const Icon = i < step ? Check : s.icon;
          return (
            <li key={s.label}>
              <button
                onClick={() => i < step && setStep(i)}
                disabled={i > step}
                className={`flex w-full items-center gap-2 rounded-xl border px-3 py-2 text-left text-xs font-semibold transition ${i === step ? "border-sky-200 bg-sky-50 text-sky-900" : i < step ? "border-line bg-white text-ink-soft hover:bg-slate-50" : "border-line bg-slate-50 text-ink-mute"}`}
              >
                <Icon size={14} className="shrink-0" />
                <span className="truncate">{s.label}</span>
              </button>
            </li>
          );
        })}
      </ol>

      <AnimatePresence mode="wait">
        <motion.div key={step} initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -12 }} transition={{ duration: 0.18 }}>
          {step === 0 && (
            <Card title="Entreprise" icon={Building2}>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Raison sociale"><input className="input" value={entreprise.raison_sociale} onChange={(e) => setEntreprise({ ...entreprise, raison_sociale: e.target.value })} maxLength={120} autoComplete="organization" /></Field>
                <Field label="Secteur d'activité">
                  <select className="select" value={entreprise.secteur} onChange={(e) => setEntreprise({ ...entreprise, secteur: e.target.value })}>
                    <option value="">Choisir…</option>
                    {SECTEURS.map((s) => <option key={s}>{s}</option>)}
                  </select>
                </Field>
                <Field label="Pays du siège"><input className="input" value={entreprise.pays} onChange={(e) => setEntreprise({ ...entreprise, pays: e.target.value })} maxLength={120} autoComplete="country-name" /></Field>
                <Field label="Taille">
                  <select className="select" value={entreprise.taille} onChange={(e) => setEntreprise({ ...entreprise, taille: e.target.value as (typeof TAILLES)[number] })}>
                    {TAILLES.map((t) => <option key={t}>{t}</option>)}
                  </select>
                </Field>
              </div>
            </Card>
          )}

          {step === 1 && (
            <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2">
                <Choice active={source === "chaine"} onClick={() => setSource("chaine")} icon={Network} title="Décrire ma chaîne" text="Sites, fournisseurs clés et produits. Recommandé : les alertes portent sur vos vrais flux." />
                <Choice active={source === "gabarit"} onClick={() => setSource("gabarit")} icon={Factory} title="Partir d'un gabarit sectoriel" text="Une chaîne type, avec des fournisseurs fictifs, à remplacer plus tard par les vôtres." />
              </div>

              {source === "gabarit" ? (
                <Card title="Gabarit">
                  <select className="select" value={gabarit} onChange={(e) => setGabarit(e.target.value)}>
                    {params?.gabarits.map((g) => <option key={g.id} value={g.id}>{g.label} ({g.noeuds} nœuds)</option>)}
                  </select>
                </Card>
              ) : (
                <>
                  <ListCard title="Vos sites" hint="Usines ou entrepôts à protéger." onAdd={() => setSites([...sites, vide.site()])}>
                    {sites.map((s, i) => (
                      <Row key={i} onRemove={sites.length > 1 ? () => setSites(sites.filter((_, j) => j !== i)) : undefined}>
                        <input className="input" placeholder="Nom du site" value={s.nom} onChange={(e) => setSites(upd(sites, i, { nom: e.target.value }))} />
                        <input className="input" placeholder="Ville" value={s.ville} onChange={(e) => setSites(upd(sites, i, { ville: e.target.value }))} />
                        <input className="input" placeholder="Pays" value={s.pays} onChange={(e) => setSites(upd(sites, i, { pays: e.target.value }))} />
                        <Num label="Stock (jours)" value={s.stock_jours} onChange={(v) => setSites(upd(sites, i, { stock_jours: v }))} max={365} />
                      </Row>
                    ))}
                  </ListCard>

                  <ListCard title="Fournisseurs clés" hint="Pour chaque site : ce qu'il reçoit et la part assurée par chaque fournisseur." onAdd={() => setFournisseurs([...fournisseurs, vide.fournisseur(nomsSites[0])])}>
                    {fournisseurs.map((f, i) => (
                      <Row key={i} onRemove={fournisseurs.length > 1 ? () => setFournisseurs(fournisseurs.filter((_, j) => j !== i)) : undefined}>
                        <input className="input" placeholder="Nom du fournisseur" value={f.nom} onChange={(e) => setFournisseurs(upd(fournisseurs, i, { nom: e.target.value }))} />
                        <input className="input" placeholder="Ville" value={f.ville} onChange={(e) => setFournisseurs(upd(fournisseurs, i, { ville: e.target.value }))} />
                        <input className="input" placeholder="Pays" value={f.pays} onChange={(e) => setFournisseurs(upd(fournisseurs, i, { pays: e.target.value }))} />
                        <input className="input" placeholder="Fourniture (ex. principe actif)" value={f.categorie} onChange={(e) => setFournisseurs(upd(fournisseurs, i, { categorie: e.target.value }))} />
                        <select className="select" value={f.site} onChange={(e) => setFournisseurs(upd(fournisseurs, i, { site: e.target.value }))}>
                          <option value="">Site livré…</option>
                          {nomsSites.map((n) => <option key={n}>{n}</option>)}
                        </select>
                        <Num label="Part (%)" value={f.part_pct} onChange={(v) => setFournisseurs(upd(fournisseurs, i, { part_pct: v }))} min={1} max={100} />
                        <select className="select" value={f.passage} onChange={(e) => setFournisseurs(upd(fournisseurs, i, { passage: e.target.value }))}>
                          <option value="">Livraison directe</option>
                          {points.filter((p) => p.nom.trim()).map((p) => <option key={p.nom} value={p.nom}>Via {p.nom}</option>)}
                        </select>
                        <label className="flex items-center gap-2 text-xs font-medium text-ink-soft">
                          <input type="checkbox" checked={f.critique} onChange={(e) => setFournisseurs(upd(fournisseurs, i, { critique: e.target.checked }))} />
                          Difficile à remplacer
                        </label>
                      </Row>
                    ))}
                  </ListCard>

                  <ListCard title="Points logistiques (facultatif)" hint="Ports ou plateformes par lesquels transitent vos approvisionnements." onAdd={() => setPoints([...points, vide.point()])}>
                    {points.length === 0 && <p className="text-xs text-ink-mute">Aucun point logistique.</p>}
                    {points.map((p, i) => (
                      <Row key={i} onRemove={() => setPoints(points.filter((_, j) => j !== i))}>
                        <input className="input" placeholder="Nom (ex. Port d'Anvers)" value={p.nom} onChange={(e) => setPoints(upd(points, i, { nom: e.target.value }))} />
                        <input className="input" placeholder="Ville" value={p.ville} onChange={(e) => setPoints(upd(points, i, { ville: e.target.value }))} />
                        <input className="input" placeholder="Pays" value={p.pays} onChange={(e) => setPoints(upd(points, i, { pays: e.target.value }))} />
                        <select className="select" value={p.type} onChange={(e) => setPoints(upd(points, i, { type: e.target.value as Point["type"] }))}>
                          <option value="port">Port</option>
                          <option value="hub">Plateforme / fret aérien</option>
                        </select>
                      </Row>
                    ))}
                  </ListCard>

                  <ListCard title="Produits finis" hint="Ce que vos sites livrent à vos clients." onAdd={() => setProduits([...produits, vide.produit(nomsSites[0])])}>
                    {produits.map((p, i) => (
                      <Row key={i} onRemove={produits.length > 1 ? () => setProduits(produits.filter((_, j) => j !== i)) : undefined}>
                        <input className="input" placeholder="Nom du produit" value={p.nom} onChange={(e) => setProduits(upd(produits, i, { nom: e.target.value }))} />
                        <select className="select" value={p.site} onChange={(e) => setProduits(upd(produits, i, { site: e.target.value }))}>
                          <option value="">Site de production…</option>
                          {nomsSites.map((n) => <option key={n}>{n}</option>)}
                        </select>
                      </Row>
                    ))}
                  </ListCard>

                  <label className="card flex cursor-pointer items-start gap-3 p-4">
                    <input type="checkbox" className="mt-1" checked={pseudo} onChange={(e) => setPseudo(e.target.checked)} />
                    <span>
                      <span className="flex items-center gap-2 text-sm font-bold"><EyeOff size={15} className="text-ink-mute" /> Pseudonymiser les fournisseurs</span>
                      <span className="mt-1 block text-xs text-ink-soft">
                        Les noms de vos fournisseurs ne sont pas conservés : ils deviennent « Fournisseur A », « Fournisseur B »… La surveillance météo et logistique de leurs sites est inchangée, mais les articles de presse qui les citent par leur nom ne pourront plus leur être rattachés.
                      </span>
                    </span>
                  </label>
                </>
              )}
            </div>
          )}

          {step === 2 && (
            <div className="space-y-4">
              <Card title="Interlocuteur" icon={UserRound}>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="Prénom"><input className="input" value={contact.prenom} onChange={(e) => setContact({ ...contact, prenom: e.target.value })} maxLength={60} autoComplete="given-name" /></Field>
                  <Field label="Nom"><input className="input" value={contact.nom} onChange={(e) => setContact({ ...contact, nom: e.target.value })} maxLength={60} autoComplete="family-name" /></Field>
                  <Field label="E-mail professionnel"><input className="input" type="email" value={contact.email} onChange={(e) => setContact({ ...contact, email: e.target.value })} maxLength={120} autoComplete="email" /></Field>
                  <Field label="Fonction (facultatif)"><input className="input" value={contact.fonction} onChange={(e) => setContact({ ...contact, fonction: e.target.value })} maxLength={80} autoComplete="organization-title" /></Field>
                </div>
                <p className="mt-3 text-xs text-ink-mute">Aucun numéro de téléphone ni donnée personnelle supplémentaire n'est demandé.</p>
              </Card>
              <Notice annees={params?.conservation_annees ?? 3} version={params?.version_notice} />
            </div>
          )}

          {step === 3 && (
            <div className="space-y-4">
              <Card title="Récapitulatif" icon={ShieldCheck}>
                <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
                  <Item k="Entreprise" v={`${entreprise.raison_sociale} · ${entreprise.secteur} · ${entreprise.taille}`} />
                  <Item k="Interlocuteur" v={`${contact.prenom} ${contact.nom} · ${contact.email}`} />
                  <Item k="Chaîne" v={source === "gabarit" ? `Gabarit : ${params?.gabarits.find((g) => g.id === gabarit)?.label ?? gabarit}`
                    : `${sites.length} site(s), ${fournisseurs.length} fournisseur(s), ${points.length} point(s) logistique(s), ${produits.length} produit(s)`} />
                  <Item k="Fournisseurs" v={source === "gabarit" ? "fictifs (gabarit)" : pseudo ? "pseudonymisés" : "nommés"} />
                </dl>
              </Card>
              <div className="card space-y-3 p-5 text-sm">
                <Consent checked={accords.traitement} onChange={(v) => setAccords({ ...accords, traitement: v })}>
                  J'ai pris connaissance de la notice d'information et j'accepte le traitement décrit, nécessaire à la création et au fonctionnement de l'espace client.
                </Consent>
                <Consent checked={accords.habilitation} onChange={(v) => setAccords({ ...accords, habilitation: v })}>
                  Je suis habilité(e) à communiquer ces informations au nom de mon entreprise.
                </Consent>
              </div>
            </div>
          )}
        </motion.div>
      </AnimatePresence>

      {erreur && <div className="rounded-xl border border-orange-100 bg-orange-50/70 px-4 py-2.5 text-sm text-orange-900">{erreur}</div>}

      <div className="flex items-center justify-between">
        <button className="btn-ghost" onClick={() => setStep(step - 1)} disabled={step === 0 || busy}>
          <ArrowLeft size={15} /> Retour
        </button>
        {step < 3 ? (
          <button className="btn bg-ink text-white hover:bg-slate-800" onClick={() => { setErreur(null); setStep(step + 1); }} disabled={!valide[step]}>
            Continuer <ArrowRight size={15} />
          </button>
        ) : (
          <button className="btn bg-ink text-white hover:bg-slate-800" onClick={envoyer} disabled={!valide.every(Boolean) || busy || !params}>
            {busy ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
            {busy ? "Création en cours…" : "Créer l'espace client"}
          </button>
        )}
      </div>
    </div>
  );
}

function upd<T>(list: T[], i: number, patch: Partial<T>): T[] {
  return list.map((x, j) => (j === i ? { ...x, ...patch } : x));
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="label">{label}</span>
      {children}
    </label>
  );
}

function Num({ label, value, onChange, min = 0, max }: { label: string; value: number; onChange: (v: number) => void; min?: number; max: number }) {
  return (
    <label className="flex items-center gap-2">
      <span className="whitespace-nowrap text-xs text-ink-mute">{label}</span>
      <input className="input w-20" type="number" min={min} max={max} value={value} onChange={(e) => onChange(Math.min(max, Math.max(min, Number(e.target.value) || min)))} />
    </label>
  );
}

function Choice({ active, onClick, icon: Icon, title, text }: { active: boolean; onClick: () => void; icon: LucideIcon; title: string; text: string }) {
  return (
    <button onClick={onClick} className={`card flex items-start gap-3 p-4 text-left transition ${active ? "border-sky-300 ring-2 ring-sky-100" : "hover:bg-slate-50"}`}>
      <Icon size={18} className={active ? "text-sky-700" : "text-ink-mute"} />
      <span>
        <span className="block text-sm font-bold">{title}</span>
        <span className="mt-1 block text-xs text-ink-soft">{text}</span>
      </span>
    </button>
  );
}

function ListCard({ title, hint, onAdd, children }: { title: string; hint: string; onAdd: () => void; children: ReactNode }) {
  return (
    <Card title={title} action={<button className="btn-ghost px-2.5 py-1.5 text-xs" onClick={onAdd}><Plus size={14} /> Ajouter</button>}>
      <p className="-mt-2 mb-3 text-xs text-ink-mute">{hint}</p>
      <div className="space-y-2">{children}</div>
    </Card>
  );
}

function Row({ children, onRemove }: { children: ReactNode; onRemove?: () => void }) {
  return (
    <div className="flex items-start gap-2 rounded-xl border border-line bg-slate-50/50 p-2">
      <div className="grid flex-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">{children}</div>
      <button className="rounded-lg p-2 text-ink-mute hover:bg-white hover:text-rose-600 disabled:opacity-30" onClick={onRemove} disabled={!onRemove} aria-label="Supprimer la ligne">
        <Trash2 size={15} />
      </button>
    </div>
  );
}

function Item({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <dt className="label">{k}</dt>
      <dd className="text-ink">{v}</dd>
    </div>
  );
}

function Consent({ checked, onChange, children }: { checked: boolean; onChange: (v: boolean) => void; children: ReactNode }) {
  return (
    <label className="flex cursor-pointer items-start gap-3">
      <input type="checkbox" className="mt-1" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="text-ink-soft">{children}</span>
    </label>
  );
}

function Notice({ annees, version }: { annees: number; version?: string }) {
  const lignes: [string, string][] = [
    ["Responsable", "l'équipe A.E.G.I.S., éditrice du service."],
    ["Finalités", "création et gestion de l'espace client, surveillance des risques de la chaîne déclarée, échanges liés au service."],
    ["Base légale", "mesures précontractuelles et exécution du contrat (article 6.1.b du RGPD)."],
    ["Données", "identité et coordonnées professionnelles de l'interlocuteur. Les informations sur la chaîne d'approvisionnement sont des données d'entreprise, conservées séparément et traitées comme confidentielles."],
    ["Destinataires", "l'équipe A.E.G.I.S. uniquement. Aucune cession ni usage commercial. Les analyses, y compris par intelligence artificielle, sont réalisées sur nos serveurs ; seuls des noms de villes sont transmis au service de géolocalisation Open-Meteo."],
    ["Conservation", `${annees} ans après le dernier contact, puis suppression.`],
    ["Vos droits", `accès, rectification, effacement, limitation, opposition et portabilité, auprès de ${CONTACT_RGPD}. Vous pouvez introduire une réclamation auprès de la CNIL (cnil.fr).`],
  ];
  return (
    <section className="card p-5">
      <h2 className="flex items-center gap-2 text-[15px] font-bold"><ShieldCheck size={17} className="text-ink-mute" /> Protection des données</h2>
      <dl className="mt-3 space-y-2 text-xs leading-relaxed text-ink-soft">
        {lignes.map(([k, v]) => (
          <div key={k} className="grid gap-1 sm:grid-cols-[110px_1fr]">
            <dt className="font-semibold text-ink">{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      {version && <p className="mt-3 text-[11px] text-ink-mute">Notice version {version}</p>}
    </section>
  );
}

function Confirmation({ r, societe, onAnalyse }: { r: InscriptionResultat; societe: string; onAnalyse: () => void }) {
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div className="card p-6 text-center">
        <CheckCircle2 size={36} className="mx-auto text-emerald-500" />
        <h1 className="mt-3 text-xl font-extrabold tracking-tight">Espace client créé</h1>
        <p className="mt-1 text-sm text-ink-soft">
          La chaîne de {societe} compte {r.noeuds} nœuds et {r.liens} liens. Elle est disponible en mode live et dispose d'un scénario modèle à compléter.
        </p>
        <button className="btn mx-auto mt-5 bg-ink text-white hover:bg-slate-800" onClick={onAnalyse}>
          Analyser cette chaîne <ArrowRight size={15} />
        </button>
      </div>
      {r.points_faibles.length > 0 && (
        <Card title="Premiers points de vigilance">
          <ul className="list-disc space-y-1 pl-5 text-sm text-ink-soft">
            {r.points_faibles.map((p) => <li key={p}>{p}</li>)}
          </ul>
        </Card>
      )}
      <Card title="Vos données">
        <p className="text-sm text-ink-soft">
          Identifiant client : <code className="rounded bg-slate-100 px-1.5">{r.client_id}</code>. Conservez-le : il permet d'exporter ou de supprimer vos données. Conservation jusqu'au {new Date(r.conservation_jusqu_au).toLocaleDateString("fr-FR")}, sauf nouveau contact.
        </p>
        <a className="btn-ghost mt-3 w-fit" href={`${API_URL}/clients/${r.client_id}/export`} target="_blank" rel="noreferrer">
          <Download size={15} /> Exporter mes données (JSON)
        </a>
      </Card>
    </div>
  );
}
