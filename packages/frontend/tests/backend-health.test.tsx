/**
 * The cold-start banner. Two things matter: that a healthy backend produces no banner
 * at all, and that a slow one produces the banner *before* the answer would have
 * arrived — the whole point is to explain a wait while it is still happening.
 */

import { describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";

import { BackendStatusBanner } from "@/components/gta/backend-status-banner";
import { LandingContent } from "@/components/gta/landing-content";
import { LocaleProvider } from "@/i18n/locale-provider";
import { GIVE_UP_AFTER_MS, SLOW_AFTER_MS } from "@/hooks/use-backend-health";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/",
}));

const WAKING = /The server is waking up/;
const UNREACHABLE = /The server is not responding/;

/** A health check that does not answer until the test says so. */
function stubHealth() {
  let settle!: (outcome: Response | Error) => void;
  const fetchMock = vi.fn(
    (_url: string, init: RequestInit) =>
      new Promise<Response>((resolve, reject) => {
        settle = (outcome) => (outcome instanceof Error ? reject(outcome) : resolve(outcome));
        init.signal?.addEventListener("abort", () =>
          reject(new DOMException("The operation was aborted.", "AbortError")),
        );
      }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return {
    fetchMock,
    // flush the promise callbacks the resolution schedules, so React has committed
    respond: async (outcome: Response | Error) => {
      await act(async () => {
        settle(outcome);
        await Promise.resolve();
      });
    },
  };
}

function renderBanner() {
  return render(
    <LocaleProvider>
      <BackendStatusBanner />
    </LocaleProvider>,
  );
}

/** Move time forward inside act(), so state updates from timers are committed. */
async function elapse(ms: number) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
    await Promise.resolve();
  });
}

/**
 * Let a settled promise's callbacks run. Not waitFor(): under fake timers its polling
 * never fires, so it would hang rather than fail.
 */
async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("the health check", () => {
  it("probes /health once, and nothing else", async () => {
    const { fetchMock } = stubHealth();
    renderBanner();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/v1/tax/health");
    // a cached 200 would report a sleeping instance as awake
    expect(init).toMatchObject({ cache: "no-store" });
    // GET: no method and no body, so it costs the backend nothing and no LLM call
    expect(init.method).toBeUndefined();
    expect(init.body).toBeUndefined();
  });

  it("says nothing at all while the check is in flight", () => {
    stubHealth();
    renderBanner();

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("says nothing once the backend answers — a healthy server is not news", async () => {
    const { respond } = stubHealth();
    renderBanner();

    await respond(new Response(JSON.stringify({ status: "ok" }), { status: 200 }));

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

describe("a cold start", () => {
  it("warns after two seconds, and not before", async () => {
    vi.useFakeTimers();
    stubHealth();
    renderBanner();

    await elapse(SLOW_AFTER_MS - 1);
    expect(screen.queryByText(WAKING)).not.toBeInTheDocument();

    await elapse(1);
    expect(screen.getByText(WAKING)).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("clears the warning when the instance finishes booting", async () => {
    vi.useFakeTimers();
    const { respond } = stubHealth();
    renderBanner();

    await elapse(SLOW_AFTER_MS);
    expect(screen.getByText(WAKING)).toBeInTheDocument();

    // ~50s later on Render's free tier, the instance is up
    await elapse(48_000);
    await respond(new Response(JSON.stringify({ status: "ok" }), { status: 200 }));

    expect(screen.queryByText(WAKING)).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("stops calling it a boot once the wait is longer than any boot", async () => {
    vi.useFakeTimers();
    stubHealth();
    renderBanner();

    await elapse(SLOW_AFTER_MS);
    expect(screen.getByText(WAKING)).toBeInTheDocument();

    // the give-up timer aborts the request, which is what flips the message
    await elapse(GIVE_UP_AFTER_MS);
    await flush();

    expect(screen.getByText(UNREACHABLE)).toBeInTheDocument();
    expect(screen.queryByText(WAKING)).not.toBeInTheDocument();
  });
});

describe("an unreachable backend", () => {
  it("reports a refused connection", async () => {
    const { respond } = stubHealth();
    renderBanner();

    await respond(new TypeError("Failed to fetch"));

    expect(await screen.findByText(UNREACHABLE)).toBeInTheDocument();
  });

  it("reports a backend that answers but is not healthy", async () => {
    const { respond } = stubHealth();
    renderBanner();

    // reachable, so not a network error — but a 502 from the proxy in front of a
    // dead instance is not an awake backend either
    await respond(new Response("bad gateway", { status: 502 }));

    expect(await screen.findByText(UNREACHABLE)).toBeInTheDocument();
  });

  it("is reported on the landing page too, where the check also does the waking", async () => {
    const { fetchMock, respond } = stubHealth();
    render(
      <LocaleProvider>
        <LandingContent />
      </LocaleProvider>,
    );

    // the request itself is what wakes a spun-down instance, so firing it here means
    // the boot overlaps with the time spent typing the first question
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await respond(new TypeError("Failed to fetch"));
    expect(await screen.findByText(UNREACHABLE)).toBeInTheDocument();
  });

  it("says nothing more after the component is gone", async () => {
    const { respond } = stubHealth();
    const { unmount } = renderBanner();

    unmount();
    // the cleanup aborts the request; reporting into a dead tree would be a warning
    await respond(new TypeError("Failed to fetch"));

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
