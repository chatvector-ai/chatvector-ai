import type { Config } from "tailwindcss";

const config: Config = {
  theme: {
    extend: {
      colors: {
        background: "var(--background)",
        surface: "var(--surface)",
        border: "var(--border)",
        foreground: "var(--foreground)",
        muted: "var(--muted)",
        subtle: "var(--subtle)",
        accent: "var(--accent)",
        blue: "var(--blue)",
      },
    },
  },
};

export default config;
