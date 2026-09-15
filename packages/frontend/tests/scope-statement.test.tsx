/**
 * The scope page. What is being held here is that the page has no opinions of
 * its own: every year, form, limit and refusal on it came out of the backend on
 * this render, and when the backend does not answer the page says nothing rather
 * than something it remembers. A test that fed it 2025 could not tell the two
 * apart, so the fixture below is deliberately a year this build has never had.
 */

import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";

import { ScopeStatement } from "@/components/gta/scope-statement";
import { LocaleProvider } from "@/i18n/locale-provider";
import type { ScopeStatement as Scope } from "@/features/meta/api";
import { MAX_CONVERSATIONS, MAX_HISTORY_TURNS } from "@/lib/conversation-history";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/scope",
}));

/** Not 2025: a page that hard-coded the real year would still pass. */
const FIXTURE: Scope = {
  modes: [
    {
      id: "chat",
      available: true,
      reason: "",
      requires_account: false,
      storage: {
        server: "request_logs_only",
        profile_memory: "none",
        tracing: "langsmith_eu",
      },
    },
    {
      id: "tax_case",
      available: false,
      reason: "database_not_configured",
      requires_account: true,
      storage: {
        server: "case_until_deleted",
        profile_memory: "outlives_the_case",
        tracing: "langsmith_eu",
      },
    },
  ],
  tax_years: [
    {
      year: 2031,
      filing_due: "2032-07-31",
      filing_due_advised: "2033-02-28",
      voluntary_filing_until: "2035-12-31",
      forms: [
        { form: "anlage_n", categories: ["arbeitsmittel"], lines_verified: true },
        { form: "hauptvordruck", categories: ["einkommensersatzleistung"], lines_verified: false },
      ],
    },
  ],
  default_tax_year: 2031,
  limits: { cases_per_user: 2, interview_calls_per_user_per_day: 0 },
  not_supported: ["electronic_submission"],
};

function stubScope(body: Scope) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(body), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderScope() {
  return render(
    <LocaleProvider>
      <ScopeStatement />
    </LocaleProvider>,
  );
}

/** Let the stubbed fetch settle and React commit what it produced. */
async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("the scope statement", () => {
  it("shows the years the backend sends, not the ones it was written against", async () => {
    stubScope(FIXTURE);
    renderScope();
    await flush();

    expect(screen.getByText("2031")).toBeInTheDocument();
    expect(screen.getByText("2032-07-31")).toBeInTheDocument();
    expect(screen.getByText("2035-12-31")).toBeInTheDocument();
    // The sentence is translated; the year inside it is the backend's default.
    expect(screen.getByText(/New Tax Cases start on 2031/)).toBeInTheDocument();
    expect(screen.queryByText("2025")).not.toBeInTheDocument();
  });

  it("names the forms and the categories that sit on them", async () => {
    stubScope(FIXTURE);
    renderScope();
    await flush();

    expect(screen.getByText(/Anlage N/)).toBeInTheDocument();
    expect(screen.getByText(/Hauptvordruck/)).toBeInTheDocument();
    expect(screen.getByText(/Work equipment/i)).toBeInTheDocument();
  });

  it("marks a form whose line numbers are unverified", async () => {
    stubScope(FIXTURE);
    renderScope();
    await flush();

    expect(screen.getByText(/line numbers unverified/i)).toBeInTheDocument();
  });

  it("says which mode is closed and why", async () => {
    stubScope(FIXTURE);
    renderScope();
    await flush();

    // By heading: "Tax Cases" is also a limit's name, and the mode is the card.
    expect(screen.getByRole("heading", { name: "Assistant" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Tax Cases" })).toBeInTheDocument();
    // The reason is the backend's identifier turned into a sentence, not the raw code.
    expect(screen.getByText(/runs without a database/i)).toBeInTheDocument();
    expect(screen.queryByText("database_not_configured")).not.toBeInTheDocument();
  });

  it("names each store separately instead of answering with one word", async () => {
    stubScope(FIXTURE);
    renderScope();
    await flush();

    expect(screen.getByText(/No account needed/i)).toBeInTheDocument();
    expect(screen.getByText(/Needs an account/i)).toBeInTheDocument();
    expect(screen.getByText(/Nothing you type is stored on the server/i)).toBeInTheDocument();
    expect(screen.getByText(/stored on the server until you delete the case/i)).toBeInTheDocument();
    // The claim this page used to make about a chat whose history the browser keeps.
    expect(screen.queryByText(/keeps nothing about you/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/nothing carries over between questions/i)).not.toBeInTheDocument();
  });

  it("says what the browser keeps, with the numbers the code enforces", async () => {
    stubScope(FIXTURE);
    renderScope();
    await flush();

    // The backend cannot see a localStorage, so these come from the module that
    // writes it. Asserted as the constants rather than as 20 and 16: the test is
    // that the page reads them, not that they hold a particular value today.
    expect(
      screen.getByText(
        new RegExp(
          `last ${MAX_CONVERSATIONS} conversations.*last ${MAX_HISTORY_TURNS} messages`,
          "i",
        ),
      ),
    ).toBeInTheDocument();
  });

  it("does not fold the profile memory or the traces into the case", async () => {
    stubScope(FIXTURE);
    renderScope();
    await flush();

    // Deleting a case reaches neither, so "stored until you delete it" cannot be
    // the whole answer for a Tax Case (services/case_erasure.py).
    expect(screen.getByText(/are not deleted with it/i)).toBeInTheDocument();
    expect(screen.getByText(/Nothing about you is remembered/i)).toBeInTheDocument();
    expect(screen.getAllByText(/traced to LangSmith in the EU/i)).toHaveLength(2);
  });

  it("shows an untraced instance as untraced", async () => {
    stubScope({
      ...FIXTURE,
      modes: FIXTURE.modes.map((m) => ({
        ...m,
        storage: { ...m.storage, tracing: "none" },
      })),
    });
    renderScope();
    await flush();

    expect(screen.getAllByText(/sends no traces anywhere/i)).toHaveLength(2);
    expect(screen.queryByText(/LangSmith/i)).not.toBeInTheDocument();
  });

  it("says which deadline is which, and that one can be pulled forward", async () => {
    stubScope(FIXTURE);
    renderScope();
    await flush();

    expect(screen.getByText(/§ 149 Abs. 2 AO/)).toBeInTheDocument();
    expect(screen.getByText(/§ 149 Abs. 3 AO/)).toBeInTheDocument();
    expect(screen.getByText(/Vorabanforderung/)).toBeInTheDocument();
    expect(screen.getByText(/§ 108 Abs. 3 AO/)).toBeInTheDocument();
  });

  it("reads a zero limit as switched off rather than as none allowed", async () => {
    stubScope(FIXTURE);
    renderScope();
    await flush();

    expect(screen.getByText(/not limited/i)).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("shows an identifier the catalogue has no sentence for, rather than a blank", async () => {
    stubScope({ ...FIXTURE, not_supported: ["something_invented_later"] });
    renderScope();
    await flush();

    expect(screen.getByText("something_invented_later")).toBeInTheDocument();
  });

  it("claims nothing at all when the statement cannot be fetched", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(async () => {
      throw new Error("offline");
    });
    vi.stubGlobal("fetch", fetchMock);

    renderScope();
    // The hook retries for as long as a free-tier wake-up would take.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(120_000);
    });

    expect(screen.getByText(/could not be fetched/i)).toBeInTheDocument();
    expect(screen.queryByText(/2031/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Anlage N/)).not.toBeInTheDocument();
    vi.useRealTimers();
  });

  it("asks again when the reader asks it to", async () => {
    vi.useFakeTimers();
    let answer = false;
    const fetchMock = vi.fn(async () => {
      if (!answer) throw new Error("offline");
      return new Response(JSON.stringify(FIXTURE), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);

    renderScope();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(120_000);
    });
    expect(screen.getByText(/could not be fetched/i)).toBeInTheDocument();

    answer = true;
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /try again/i }));
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(screen.getByText("2031")).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("never caches the statement", async () => {
    const fetchMock = stubScope(FIXTURE);
    renderScope();
    await flush();

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.cache).toBe("no-store");
  });
});
