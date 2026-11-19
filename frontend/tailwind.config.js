/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: { sans: ['"Plus Jakarta Sans"', "Inter", "system-ui", "sans-serif"] },
      colors: {
        canvas: "#F8FAFC",
        line: "#E2E8F0",
        ink: { DEFAULT: "#0F172A", soft: "#475569", mute: "#94A3B8" },
        media: { bg: "#FEF9C3", bg2: "#FEF3C7", border: "#FDE047", text: "#854D0E" },
        finance: { bg: "#DBEAFE", bg2: "#E0F2FE", border: "#93C5FD", text: "#1E40AF" },
        weather: { bg: "#DCFCE7", bg2: "#D1FAE5", border: "#86EFAC", text: "#166534" },
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
