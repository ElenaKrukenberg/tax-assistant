"use client";

import { useState } from "react";

import { getSaveHistory, getShowTrace } from "@/lib/preferences";

/**
 * The two preferences the chat page reads while rendering.
 *
 * Read in a lazy initializer rather than in an effect, because both of them gate an
 * effect of their own: correcting the value one commit later would let the history
 * load fire once with the default before the real answer arrived - which is how
 * "history is off" still ended up listing the conversations of an earlier visit.
 *
 * Hydration is safe despite localStorage being client-only: at first paint there are
 * no messages, so nothing either preference controls is on the page yet. The server's
 * markup and the browser's first render agree whatever is stored.
 */

function useStoredFlag(read: () => boolean): boolean {
  const [value] = useState(() => (typeof window === "undefined" ? true : read()));
  return value;
}

export function useShowTrace(): boolean {
  return useStoredFlag(getShowTrace);
}

export function useSaveHistory(): boolean {
  return useStoredFlag(getSaveHistory);
}
