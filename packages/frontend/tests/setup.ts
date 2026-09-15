/**
 * jsdom is a document, not a browser: the APIs below exist in every browser the app
 * runs in but are absent or incomplete here, and the components use them during a
 * normal render. Each shim is here because something failed without it — not
 * pre-emptively.
 */

import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup, configure } from "@testing-library/react";

// The default 1s is close to what a cold render of the chat page plus a stubbed
// request costs on a loaded machine, which showed up as a flaky timeout rather than
// a failing assertion. Waiting longer costs nothing when the query resolves early.
configure({ asyncUtilTimeout: 5000 });

// Radix (dropdowns, collapsibles) measures and positions its layers.
if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
}

// Radix reads pointer capture and scrolls items into view; jsdom implements neither.
const elementStubs: Record<string, () => unknown> = {
  scrollIntoView: () => undefined,
  releasePointerCapture: () => undefined,
  hasPointerCapture: () => false,
};
for (const [method, stub] of Object.entries(elementStubs)) {
  if (!(method in Element.prototype)) {
    Object.defineProperty(Element.prototype, method, { value: stub, configurable: true });
  }
}

// Message and conversation ids come from crypto.randomUUID().
if (!globalThis.crypto?.randomUUID) {
  let counter = 0;
  Object.defineProperty(globalThis, "crypto", {
    value: { ...globalThis.crypto, randomUUID: () => `uuid-${++counter}` },
    configurable: true,
  });
}

afterEach(() => {
  cleanup();
  // Conversations and the pending-question handoff live in web storage, so a test
  // that wrote one must not be visible to the next.
  localStorage.clear();
  sessionStorage.clear();
  vi.useRealTimers();
});
