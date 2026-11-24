// Session de l'utilisateur connecté : jeton et profil, conservés le temps de l'onglet (sessionStorage).
export interface Profil {
  role: "client" | "equipe";
  email: string;
  nom: string;
  societe: string | null;
  client_id: string | null;
  topology_ref: string | null;
}

const CLE = "aegis.session";

function lire(): { jeton: string; profil: Profil } | null {
  try {
    const brut = sessionStorage.getItem(CLE);
    return brut ? JSON.parse(brut) : null;
  } catch {
    return null;
  }
}

export const session = {
  jeton: () => lire()?.jeton ?? null,
  profil: () => lire()?.profil ?? null,
  ouvrir(jeton: string, profil: Profil) {
    try {
      sessionStorage.setItem(CLE, JSON.stringify({ jeton, profil }));
    } catch {
      /* stockage indisponible : la session ne survivra pas au rechargement */
    }
    window.dispatchEvent(new Event("aegis-session"));
  },
  fermer() {
    try {
      sessionStorage.removeItem(CLE);
    } catch {
      /* rien à effacer */
    }
    window.dispatchEvent(new Event("aegis-session"));
  },
};
