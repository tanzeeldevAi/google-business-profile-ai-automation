import type { Config } from "tailwindcss";

/**
 * Google's own palette, not an approximation.
 * Blue 600 #1a73e8 is the primary Google uses across Search, Maps and the
 * Business Profile console; the greys are Material's, which is why the UI
 * reads as "a Google product" rather than "a dark dashboard".
 */
export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        g: {
          blue: "#1a73e8",
          blueHover: "#1b66c9",
          blueLight: "#e8f0fe",
          green: "#1e8e3e",
          greenLight: "#e6f4ea",
          yellow: "#f9ab00",
          yellowLight: "#fef7e0",
          red: "#d93025",
          redLight: "#fce8e6",
          grey900: "#202124",
          grey700: "#3c4043",
          grey600: "#5f6368",
          grey500: "#80868b",
          grey300: "#dadce0",
          grey200: "#e8eaed",
          grey100: "#f1f3f4",
          grey50: "#f8f9fa",
          white: "#ffffff",
        },
      },
      fontFamily: {
        sans: ['"Google Sans"', '"Product Sans"', "Roboto", "system-ui",
               "-apple-system", '"Segoe UI"', "Arial", "sans-serif"],
        text: ["Roboto", "system-ui", "-apple-system", '"Segoe UI"', "Arial",
               "sans-serif"],
        mono: ['"Roboto Mono"', "ui-monospace", "Menlo", "Consolas", "monospace"],
      },
      boxShadow: {
        // Material elevation 1 / 2 / 3, as Google actually renders them.
        e1: "0 1px 2px 0 rgba(60,64,67,.30), 0 1px 3px 1px rgba(60,64,67,.15)",
        e2: "0 1px 2px 0 rgba(60,64,67,.30), 0 2px 6px 2px rgba(60,64,67,.15)",
        e3: "0 4px 8px 3px rgba(60,64,67,.15), 0 1px 3px rgba(60,64,67,.30)",
      },
      borderRadius: { g: "8px", pill: "9999px" },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        indeterminate: {
          "0%": { left: "-40%", width: "40%" },
          "60%": { left: "100%", width: "40%" },
          "100%": { left: "100%", width: "40%" },
        },
        "ripple-out": {
          "0%": { transform: "scale(0)", opacity: "0.28" },
          "100%": { transform: "scale(2.6)", opacity: "0" },
        },
        "dial-in": { "0%": { strokeDasharray: "0 999" } },
      },
      animation: {
        "fade-up": "fade-up .28s cubic-bezier(.4,0,.2,1) both",
        indeterminate: "indeterminate 1.6s cubic-bezier(.4,0,.2,1) infinite",
        "ripple-out": "ripple-out .5s cubic-bezier(.4,0,.2,1) forwards",
      },
    },
  },
  plugins: [],
} satisfies Config;
