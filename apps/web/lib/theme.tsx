"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { readStored, writeStored } from "./storage";

export type Theme = "light" | "dark" | "system";
const STORAGE_KEY = "fitcher.theme";
const THEMES: Theme[] = ["light", "dark", "system"];

type ThemeState = { theme: Theme; setTheme: (theme: Theme) => void };
const ThemeContext = createContext<ThemeState | null>(null);

/** Light or dark follows the system setting unless the user picks one (DECISIONS §15); kept per browser. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>("system");

  useEffect(() => {
    const stored = readStored(STORAGE_KEY);
    if (stored && THEMES.includes(stored as Theme)) setThemeState(stored as Theme);
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
  }, [theme]);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    writeStored(STORAGE_KEY, next);
  }, []);

  const value = useMemo(() => ({ theme, setTheme }), [theme, setTheme]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeState {
  const context = useContext(ThemeContext);
  if (context === null) throw new Error("useTheme needs a ThemeProvider");
  return context;
}
