"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { applyTheme, getTheme, setTheme as persistTheme, type Theme } from "@/lib/preferences";

/**
 * Holds the chosen theme and keeps the `.dark` class on <html> in step with it.
 *
 * The class is already correct before this mounts - the inline script in
 * app/layout.tsx runs first, so there is no flash - and what this adds is the two
 * things a script cannot do: let the Settings control change the choice, and keep
 * "system" honest when the OS switches to dark at sunset while the tab is open.
 */

const ThemeContext = createContext<{ theme: Theme; setTheme: (t: Theme) => void }>({
  theme: "system",
  setTheme: () => {},
});

export function useTheme() {
  return useContext(ThemeContext);
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  // "system" on the server and the first client render, then the stored choice,
  // exactly as LocaleProvider does it: localStorage is client-only and reading it
  // during render would make the markup disagree with itself.
  const [theme, setThemeState] = useState<Theme>("system");

  useEffect(() => {
    setThemeState(getTheme());
  }, []);

  useEffect(() => {
    applyTheme(theme);
    if (theme !== "system") return;

    // Only "system" follows the OS, and only while it is the choice - a listener
    // left running after the user picks light would fight their own setting.
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyTheme("system");
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [theme]);

  function setTheme(next: Theme) {
    persistTheme(next);
    setThemeState(next);
  }

  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>;
}
