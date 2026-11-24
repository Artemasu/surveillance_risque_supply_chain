// Identité visuelle A.E.G.I.S. : trois couleurs de marque, une par agent.
//   bleu canard #017F8D (finance, couleur principale) · vert olive #A2B153 (météo) · jaune moutarde #ECB920 (médias).
// Les palettes sky / cyan, emerald et amber / yellow de Tailwind sont remplacées par ces teintes : toutes les classes
// existantes (bg-sky-50, text-emerald-700...) suivent la charte sans modifier les composants.
const canard = {50:"#EEF7F8",100:"#D6EDEF",200:"#ADDADF",300:"#7FC2C9",400:"#3FA0AA",500:"#0F8C99",600:"#017F8D",700:"#016A76",800:"#01545D",900:"#013F46",950:"#012B30"};
const olive = {50:"#F6F8EC",100:"#EBF0D3",200:"#D8E1A9",300:"#C2CF7E",400:"#AFBE63",500:"#A2B153",600:"#8A9A3B",700:"#6E7B2E",800:"#555F24",900:"#3E461A",950:"#282D11"};
const moutarde = {50:"#FEF8E7",100:"#FBEFC6",200:"#F7DF8D",300:"#F2CD55",400:"#EFC33A",500:"#ECB920",600:"#C99A00",700:"#9C7700",800:"#765A00",900:"#574300",950:"#3A2C00"};

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', "Inter", "system-ui", "sans-serif"],
        display: ['"Space Grotesk"', '"Plus Jakarta Sans"', "system-ui", "sans-serif"],   // titres de la page vitrine
      },
      colors: {
        canvas: "#F8FAFC",
        nuit: "#061417",          // fond sombre de la page vitrine
        creme: "#F4F1EA",         // fond chaud des sections claires de la page vitrine
        brand: { canard: "#017F8D", olive: "#A2B153", moutarde: "#ECB920" },
        sky: canard,
        cyan: canard,
        emerald: olive,
        amber: moutarde,
        yellow: moutarde,
        line: "#E2E8F0",
        ink: { DEFAULT: "#0F172A", soft: "#475569", mute: "#94A3B8" },
        media: { bg: "#FBF1D0", bg2: "#FDF6E1", border: "#ECB920", text: "#6E5200" },
        finance: { bg: "#D6EDEF", bg2: "#E8F4F5", border: "#5FAFB8", text: "#01545D" },
        weather: { bg: "#EEF2DC", bg2: "#F4F6E8", border: "#A2B153", text: "#4A5520" },
        lvl: {
          ok: "#10B981", okbg: "#ECFDF5",
          info: "#D97706", infobg: "#FFFBEB",
          warning: "#EA580C", warningbg: "#FFF7ED",
          critical: "#BE123C", criticalbg: "#FFF1F2",
        },
      },
      boxShadow: { soft: "0 1px 2px rgba(15,23,42,.04), 0 4px 16px rgba(15,23,42,.05)" },
    },
  },
  plugins: [],
};
