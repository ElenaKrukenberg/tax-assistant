"use client";

import { useEffect, useState } from "react";

/**
 * Is the API there, and is it awake?
 *
 * The backend runs on Render's free plan, which spins the instance down after a
 * quarter of an hour of idleness. The next request pays the cold start — around
 * fifty seconds — and until now the user met that delay *after* sending a question,
 * with nothing on screen to say why. So the check runs on page load instead: it
 * both reports the wait and causes the wake-up, which means the boot overlaps with
 * the time the user spends typing rather than following it.
 *
 * `/health` is the right probe for this: no LLM call, no rate limit, and it is the
 * same path Render's own health check uses.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type BackendStatus = "checking" | "ok" | "waking" | "unreachable";

// A warm instance answers /health in tens of milliseconds, so anything past this is
// not "the network is slow" — it is a cold start. Short enough that the banner is up
// long before the user has finished typing.
export const SLOW_AFTER_MS = 2000;

// A cold start is ~50s; past this the instance is not waking, it is down.
export const GIVE_UP_AFTER_MS = 90_000;

export function useBackendHealth(): BackendStatus {
  const [status, setStatus] = useState<BackendStatus>("checking");

  useEffect(() => {
    const controller = new AbortController();
    let done = false; // unmounted, or already reported: nobody left to tell

    const slow = setTimeout(
      () => setStatus((current) => (current === "checking" ? "waking" : current)),
      SLOW_AFTER_MS,
    );
    const giveUp = setTimeout(() => controller.abort(), GIVE_UP_AFTER_MS);

    function settle(next: BackendStatus) {
      clearTimeout(slow);
      clearTimeout(giveUp);
      if (!done) setStatus(next);
    }

    // cache: "no-store" — a cached 200 would report a sleeping instance as awake
    fetch(`${API_URL}/api/v1/tax/health`, { signal: controller.signal, cache: "no-store" })
      .then((response) => settle(response.ok ? "ok" : "unreachable"))
      .catch(() => settle("unreachable"));

    return () => {
      done = true;
      clearTimeout(slow);
      clearTimeout(giveUp);
      controller.abort();
    };
  }, []);

  return status;
}
