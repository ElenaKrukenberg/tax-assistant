/**
 * The Settings screen's preferences, and the only place their storage keys are
 * written. Everything here is per-browser: these are display and client-side
 * choices, not account data, so none of them travels to the server except
 * `depth`, which the chat request carries as a field.
 *
 * Plain functions rather than a hook, for the same reason `conversation-history.ts`
 * is: the pages that read a preference are not the page that sets it, and the rules
 * (what the default is, what an unreadable value means) are worth testing without
 * rendering anything.
 *
 * Every read tolerates a missing, malformed or unavailable store and answers with
 * the default. A browser with storage disabled gets the product's default
 * behaviour, not a crash - and a value written by an older build that no longer
 * parses is the same case.
 */

export type Theme = "light" | "dark" | "system";
export type Depth = "concise" | "balanced" | "detailed";

export const THEMES: readonly Theme[] = ["light", "dark", "system"];
export const DEPTHS: readonly Depth[] = ["concise", "balanced", "detailed"];

// `answer-follow-ui` keeps its name: it is already in users' browsers, and renaming
// it would silently reset the one preference that worked before this screen did.
export const KEYS = {
  theme: "theme",
  depth: "answer-depth",
  showTrace: "show-trace",
  saveHistory: "save-history",
  answersFollowUi: "answer-follow-ui",
} as const;

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null; // storage disabled or unavailable: the default applies
  }
}

function write(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* nothing to recover: the control keeps working for this session only */
  }
}

function readOneOf<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  const stored = read(key);
  return stored && (allowed as readonly string[]).includes(stored) ? (stored as T) : fallback;
}

function readFlag(key: string, fallback: boolean): boolean {
  const stored = read(key);
  return stored === null ? fallback : stored === "true";
}

export function getTheme(): Theme {
  return readOneOf(KEYS.theme, THEMES, "system");
}

export function setTheme(theme: Theme): void {
  write(KEYS.theme, theme);
}

export function getDepth(): Depth {
  return readOneOf(KEYS.depth, DEPTHS, "balanced");
}

export function setDepth(depth: Depth): void {
  write(KEYS.depth, depth);
}

// Both default to on: that is what the screen showed while the switches were inert,
// so nobody's product changes behaviour the day they became real.
export function getShowTrace(): boolean {
  return readFlag(KEYS.showTrace, true);
}

export function setShowTrace(value: boolean): void {
  write(KEYS.showTrace, String(value));
}

export function getSaveHistory(): boolean {
  return readFlag(KEYS.saveHistory, true);
}

export function setSaveHistory(value: boolean): void {
  write(KEYS.saveHistory, String(value));
}

export function getAnswersFollowUi(): boolean {
  return readFlag(KEYS.answersFollowUi, false);
}

export function setAnswersFollowUi(value: boolean): void {
  write(KEYS.answersFollowUi, String(value));
}

/** What "system" resolves to right now. Reads the OS preference, so client-only. */
export function resolvedTheme(theme: Theme): "light" | "dark" {
  if (theme !== "system") return theme;
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  } catch {
    return "light"; // no matchMedia (jsdom, very old browsers): the light palette
  }
}

/**
 * Put the palette on the document. The dark tokens live under `.dark` in
 * styles.css, so a class on <html> is the whole mechanism.
 */
export function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle("dark", resolvedTheme(theme) === "dark");
}

/**
 * The same thing the inline script in app/layout.tsx runs before first paint,
 * as a string. It is stringified rather than imported because it has to execute
 * before React hydrates - otherwise a dark-theme user sees a white flash on every
 * navigation. Kept beside the real implementation so the two cannot drift apart
 * unnoticed; a test asserts they agree.
 */
export const THEME_BOOT_SCRIPT = `(function(){try{var t=localStorage.getItem("${KEYS.theme}")||"system";var d=t==="dark"||(t==="system"&&window.matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.classList.toggle("dark",d)}catch(e){}})()`;
