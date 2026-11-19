import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
  build: {
    // MapLibre (~1 Mo) et three.js (~1,5 Mo) sont chargés à la demande (React.lazy) à l'ouverture de la carte ou de la
    // vue orbitale 3D : ils ne pèsent pas sur le premier affichage. Seuil relevé pour ces deux morceaux connus.
    chunkSizeWarningLimit: 1600,
  },
});
