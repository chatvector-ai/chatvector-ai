"use client";

import { useEffect, useState } from "react";
import { Sun, Moon } from "lucide-react";

type Theme = "light" | "dark";

function getInitialTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  const stored = localStorage.getItem("theme") as Theme | null;
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: light)").matches
    ? "light"
    : "dark";
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("dark");

  useEffect(() => {
    const initial = getInitialTheme();
    setTheme(initial);
    document.documentElement.setAttribute("data-theme", initial);
  }, []);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: light)");
    const handleChange = (e: MediaQueryListEvent) => {
      if (!localStorage.getItem("theme")) {
        const next: Theme = e.matches ? "light" : "dark";
        setTheme(next);
        document.documentElement.setAttribute("data-theme", next);
      }
    };
    media.addEventListener("change", handleChange);
    return () => media.removeEventListener("change", handleChange);
  }, []);

  const toggle = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("theme", next);
  };

  const isLight = theme === "light";

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={isLight ? "Switch to dark mode" : "Switch to light mode"}
      className="cursor-pointer rounded-md border border-border bg-transparent p-2 text-foreground transition-colors duration-200 hover:border-accent hover:bg-accent/10 hover:text-accent"
    >
      {isLight ? (
        <Sun className="size-[1.1rem]" aria-hidden />
      ) : (
        <Moon className="size-[1.1rem]" aria-hidden />
      )}
    </button>
  );
}
