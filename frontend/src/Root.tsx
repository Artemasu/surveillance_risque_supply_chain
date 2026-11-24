// Aiguillage : pages publiques (vitrine, connexion, inscription, notice) sans compte, application après connexion.
import { Suspense, lazy, useEffect, useState } from "react";
import App from "./App";
import { session } from "./session";
import { StoreProvider } from "./store";
import Landing from "./components/public/Landing";
import Login from "./components/public/Login";
import PublicShell from "./components/public/PublicShell";

const Inscription = lazy(() => import("./components/OnboardingPage"));
const Notice = lazy(() => import("./components/OnboardingPage").then((m) => ({ default: m.NoticePage })));

const Chargement = () => <div className="p-10 text-center text-sm text-ink-mute">Chargement…</div>;

export default function Root() {
  const [route, setRoute] = useState(window.location.hash);
  const [connecte, setConnecte] = useState(!!session.jeton());

  useEffect(() => {
    const surHash = () => setRoute(window.location.hash);
    const surSession = () => setConnecte(!!session.jeton());
    window.addEventListener("hashchange", surHash);
    window.addEventListener("aegis-session", surSession);
    return () => {
      window.removeEventListener("hashchange", surHash);
      window.removeEventListener("aegis-session", surSession);
    };
  }, []);

  if (connecte) {
    return (
      <StoreProvider>
        <App />
      </StoreProvider>
    );
  }
  if (route === "#/connexion") return <Login />;
  if (route === "#/inscription" || route === "#/donnees") {
    return (
      <PublicShell nav={false}>
        <div className="px-4 py-10 sm:px-6">
          <Suspense fallback={<Chargement />}>{route === "#/inscription" ? <Inscription /> : <Notice />}</Suspense>
        </div>
      </PublicShell>
    );
  }
  return <Landing />;
}
