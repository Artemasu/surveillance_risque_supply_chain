// Page de connexion : e-mail professionnel et mot de passe.
import { Loader2, LogIn, Wrench } from "lucide-react";
import { useState, type FormEvent } from "react";
import { api } from "../../api";
import { session } from "../../session";
import PublicShell, { aller } from "./PublicShell";

export default function Login() {
  const [email, setEmail] = useState("");
  const [mdp, setMdp] = useState("");
  const [busy, setBusy] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  const envoyer = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErreur(null);
    try {
      const r = await api.connexion(email.trim(), mdp);
      session.ouvrir(r.jeton, r.profil);
      aller("#/");
    } catch (err) {
      const m = (err as Error).message.replace(/^API \d+ : /, "");
      setErreur(m.charAt(0).toUpperCase() + m.slice(1));
    } finally {
      setBusy(false);
    }
  };

  // Bouton visible seulement avec « npm run dev » (absent du site compilé) ; l'API doit avoir AEGIS_DEV=1.
  const entrerDev = async () => {
    setBusy(true);
    setErreur(null);
    try {
      const r = await api.connexionDev();
      session.ouvrir(r.jeton, r.profil);
      aller("#/");
    } catch (err) {
      const m = (err as Error).message.replace(/^API \d+ : /, "");
      setErreur(m.charAt(0).toUpperCase() + m.slice(1));
    } finally {
      setBusy(false);
    }
  };

  return (
    <PublicShell nav={false}>
      <div className="mx-auto flex max-w-md flex-col px-4 py-16">
        <form onSubmit={envoyer} className="card space-y-4 p-7">
          <div>
            <h1 className="text-xl font-extrabold tracking-tight">Connexion</h1>
            <p className="mt-1 text-sm text-ink-mute">Accédez à la surveillance de votre chaîne d'approvisionnement.</p>
          </div>
          <label className="block space-y-1.5">
            <span className="label">E-mail professionnel</span>
            <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required autoFocus />
          </label>
          <label className="block space-y-1.5">
            <span className="label">Mot de passe</span>
            <input className="input" type="password" value={mdp} onChange={(e) => setMdp(e.target.value)} autoComplete="current-password" required />
          </label>
          {erreur && <p className="rounded-xl border border-orange-100 bg-orange-50/70 px-3 py-2 text-sm text-orange-900">{erreur}</p>}
          <button className="btn w-full justify-center bg-ink py-2.5 text-white hover:bg-slate-800" disabled={busy || !email || !mdp}>
            {busy ? <Loader2 size={15} className="animate-spin" /> : <LogIn size={15} />} Se connecter
          </button>
          <p className="text-center text-sm text-ink-soft">
            Pas encore de compte ? <button type="button" className="font-semibold text-sky-700 hover:underline" onClick={() => aller("#/inscription")}>Créer un espace</button>
          </p>
        </form>
        {import.meta.env.DEV && (
          <button type="button" onClick={entrerDev} disabled={busy}
            className="mt-4 inline-flex items-center justify-center gap-2 rounded-xl border border-dashed border-amber-400 bg-amber-50 px-4 py-2.5 text-sm font-semibold text-amber-900 hover:bg-amber-100">
            <Wrench size={15} /> Entrer sans mot de passe (développement)
          </button>
        )}
        <p className="mt-4 text-center text-[11px] text-ink-mute">La session se ferme à la fermeture de l'onglet et au bout de 8 heures.</p>
      </div>
    </PublicShell>
  );
}
