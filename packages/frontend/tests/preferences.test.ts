/**
 * The Settings preferences: what a fresh browser gets, what survives a round trip,
 * and what happens when the store is unusable or holds something unexpected.
 *
 * The defaults matter more than they look. Each one is what the screen showed while
 * the control was still inert, so nobody's product changes behaviour on the day the
 * switches became real - and a stored value from an older build must not be able to
 * put the app into a state no control can express.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  KEYS,
  THEME_BOOT_SCRIPT,
  applyTheme,
  getAnswersFollowUi,
  getDepth,
  getSaveHistory,
  getShowTrace,
  getTheme,
  resolvedTheme,
  setAnswersFollowUi,
  setDepth,
  setSaveHistory,
  setShowTrace,
  setTheme,
} from "@/lib/preferences";

afterEach(() => {
  document.documentElement.classList.remove("dark");
});

describe("defaults", () => {
  it("gives a fresh browser what the screen showed before the controls worked", () => {
    expect(getTheme()).toBe("system");
    expect(getDepth()).toBe("balanced");
    expect(getShowTrace()).toBe(true);
    expect(getSaveHistory()).toBe(true);
    // The one that already worked, and whose key is therefore not renamed.
    expect(getAnswersFollowUi()).toBe(false);
  });

  it("keeps the answer-follow-ui key it already had in users' browsers", () => {
    expect(KEYS.answersFollowUi).toBe("answer-follow-ui");
  });
});

describe("round trips", () => {
  it("reads back what was written", () => {
    setTheme("dark");
    setDepth("detailed");
    setShowTrace(false);
    setSaveHistory(false);
    setAnswersFollowUi(true);

    expect(getTheme()).toBe("dark");
    expect(getDepth()).toBe("detailed");
    expect(getShowTrace()).toBe(false);
    expect(getSaveHistory()).toBe(false);
    expect(getAnswersFollowUi()).toBe(true);
  });
});

describe("a stored value the app cannot use", () => {
  it("falls back to the default rather than passing it on", () => {
    // "cosy" was never a theme and "exhaustive" is a depth the API would 422.
    localStorage.setItem(KEYS.theme, "cosy");
    localStorage.setItem(KEYS.depth, "exhaustive");

    expect(getTheme()).toBe("system");
    expect(getDepth()).toBe("balanced");
  });

  it("survives a store that throws on every access", () => {
    const boom = () => {
      throw new Error("storage disabled");
    };
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(boom);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(boom);

    expect(getDepth()).toBe("balanced");
    expect(() => setDepth("concise")).not.toThrow();
  });
});

describe("applying a theme", () => {
  it("puts the dark palette on the document and takes it off again", () => {
    applyTheme("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);

    applyTheme("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("asks the OS what 'system' means", () => {
    vi.spyOn(window, "matchMedia").mockReturnValue({ matches: true } as MediaQueryList);
    expect(resolvedTheme("system")).toBe("dark");
    expect(resolvedTheme("light")).toBe("light"); // an explicit choice never asks
  });
});

describe("the inline boot script", () => {
  /**
   * The script runs before React and must reach the same conclusion as applyTheme,
   * or the page paints one palette and then switches to the other. It is a string
   * precisely because it cannot be imported, so nothing but a test can hold the two
   * together - this evaluates it and compares the result.
   */
  const boot = () => new Function(THEME_BOOT_SCRIPT)();

  it("agrees with applyTheme for every stored choice", () => {
    vi.spyOn(window, "matchMedia").mockReturnValue({ matches: true } as MediaQueryList);

    for (const theme of ["light", "dark", "system"] as const) {
      setTheme(theme);
      applyTheme(theme);
      const expected = document.documentElement.classList.contains("dark");

      document.documentElement.classList.remove("dark");
      boot();
      expect(document.documentElement.classList.contains("dark")).toBe(expected);
    }
  });

  it("paints light when nothing is stored", () => {
    vi.spyOn(window, "matchMedia").mockReturnValue({ matches: false } as MediaQueryList);
    boot();
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });
});
