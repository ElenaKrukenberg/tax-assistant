"use client";

import { useCallback, useEffect, useState } from "react";

import { fetchScope, type ScopeStatement } from "@/features/meta/api";

/**
 * What this build offers, asked once per mount.
 *
 * The statement is small and unauthenticated, but it shares a cold start with
 * everything else on the free plan: the first request after a quarter hour of
 * idleness waits for the instance to wake. So a failure is retried for as long
 * as a wake-up would plausibly take, and only then reported.
 *
 * There is no fallback copy. A hard-coded "covers 2025" that outlives the build
 * it described is the thing this hook exists to stop, so when the statement
 * cannot be fetched the caller says so rather than guessing.
 */

// Matches the cold-start window in use-backend-health.ts.
const GIVE_UP_AFTER_MS = 90_000;
const RETRY_EVERY_MS = 4_000;

export type ScopeState =
  | { status: "loading"; scope: null }
  | { status: "ready"; scope: ScopeStatement }
  | { status: "unavailable"; scope: null };

export function useScope(): ScopeState & { retry: () => void } {
  const [state, setState] = useState<ScopeState>({ status: "loading", scope: null });
  const [attempt, setAttempt] = useState(0);

  const retry = useCallback(() => {
    setState({ status: "loading", scope: null });
    setAttempt((n) => n + 1);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let done = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const deadline = Date.now() + GIVE_UP_AFTER_MS;

    function attemptFetch() {
      fetchScope(controller.signal)
        .then((scope) => {
          if (!done) setState({ status: "ready", scope });
        })
        .catch(() => {
          if (done) return;
          if (Date.now() + RETRY_EVERY_MS < deadline) {
            timer = setTimeout(attemptFetch, RETRY_EVERY_MS);
            return;
          }
          setState({ status: "unavailable", scope: null });
        });
    }

    attemptFetch();

    return () => {
      done = true;
      if (timer) clearTimeout(timer);
      controller.abort();
    };
  }, [attempt]);

  return { ...state, retry };
}
