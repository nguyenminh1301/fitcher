"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { readStored, writeStored } from "../storage";
import { DICTIONARIES, formatDate, formatNumber, LOCALES, translate, type Locale } from "./index";

const STORAGE_KEY = "fitcher.locale";

type I18n = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: string, vars?: Record<string, string | number>) => string;
  formatNumber: (value: number, options?: Intl.NumberFormatOptions) => string;
  formatDate: (iso: string, options?: Intl.DateTimeFormatOptions) => string;
};

const I18nContext = createContext<I18n | null>(null);

/** The interface language, kept per browser; content keeps its own `lang`. */
export function I18nProvider({ children, initial = "en" }: { children: ReactNode; initial?: Locale }) {
  const [locale, setLocaleState] = useState<Locale>(initial);

  useEffect(() => {
    const stored = readStored(STORAGE_KEY);
    if (stored && LOCALES.includes(stored as Locale)) setLocaleState(stored as Locale);
  }, []);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    writeStored(STORAGE_KEY, next);
  }, []);

  const value = useMemo<I18n>(
    () => ({
      locale,
      setLocale,
      t: (key, vars) => translate(DICTIONARIES.en, DICTIONARIES[locale], key, vars),
      formatNumber: (number, options) => formatNumber(number, locale, options),
      formatDate: (iso, options) => formatDate(iso, locale, options),
    }),
    [locale, setLocale],
  );
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  const context = useContext(I18nContext);
  if (context === null) throw new Error("useI18n needs an I18nProvider");
  return context;
}
