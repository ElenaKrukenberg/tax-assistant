"use client";

import { NextIntlClientProvider } from "next-intl";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import en from "./messages/en.json";
import de from "./messages/de.json";
import tr from "./messages/tr.json";
import ru from "./messages/ru.json";

export const LOCALES = ["en", "de", "tr", "ru"] as const;
export type Locale = (typeof LOCALES)[number];

const MESSAGES: Record<Locale, typeof en> = { en, de, tr, ru };
const STORAGE_KEY = "ui-locale";

const LocaleContext = createContext<{ locale: Locale; setLocale: (l: Locale) => void }>({
  locale: "en",
  setLocale: () => {},
});

export function useLocale() {
  return useContext(LocaleContext);
}

function detectLocale(): Locale {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored && (LOCALES as readonly string[]).includes(stored)) return stored as Locale;
  const nav = navigator.language.slice(0, 2).toLowerCase();
  return (LOCALES as readonly string[]).includes(nav) ? (nav as Locale) : "en";
}

export function LocaleProvider({ children }: { children: ReactNode }) {
  // render "en" on the server / first client paint, then switch after mount —
  // localStorage and navigator are client-only
  const [locale, setLocaleState] = useState<Locale>("en");

  // The document's own language, kept in step with the chosen one. `app/layout.tsx`
  // renders `lang="en"` because the locale is a client-side choice, and a screen
  // reader that is told English while reading Russian pronounces it as English (#54).
  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  useEffect(() => {
    setLocaleState(detectLocale());
  }, []);

  function setLocale(l: Locale) {
    localStorage.setItem(STORAGE_KEY, l);
    setLocaleState(l);
  }

  return (
    <LocaleContext.Provider value={{ locale, setLocale }}>
      <NextIntlClientProvider locale={locale} messages={MESSAGES[locale]} timeZone="Europe/Berlin">
        {children}
      </NextIntlClientProvider>
    </LocaleContext.Provider>
  );
}
