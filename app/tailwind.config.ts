import type { Config } from "tailwindcss";

export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: "#E8EAEE", 2: "#A2ABB8", 3: "#6C7685" },
        panel: { DEFAULT: "#171A21", 2: "#1D212A" },
        line: "#2A2F3A",
        base: "#0F1115",
        accent: "#7C9CF5",
        write: "#F0A868",
        good: "#4ADE80",
        warn: "#FBBF24",
        bad: "#F87171",
      },
      fontFamily: { mono: ["ui-monospace", "Menlo", "Consolas", "monospace"] },
    },
  },
  plugins: [],
} satisfies Config;
