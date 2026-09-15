/**
 * Offering documents before the first question.
 *
 * The mechanism was already there and invisible: a value read out of a document takes
 * its own question out of the interview, because `relevant_questions` drops anything
 * the case already knows whatever it came from. Nobody uploading first was not a bug
 * in that code - it was a product that never said so, so people went to the interview
 * first and answered questions their payslip had already answered.
 *
 * What is worth pinning is mostly when the offer does *not* appear. An offer that
 * comes back on every refresh, or over a case already half answered, is an obstacle
 * rather than a shortcut.
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { InterviewStep, LiveDocument } from "@/features/cases/api";
import { LiveInterview } from "@/components/cases/live-interview";
import { LocaleProvider } from "@/i18n/locale-provider";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/cases/case-1/interview",
}));

vi.mock("@/features/cases/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/cases/api")>()),
  advanceInterview: vi.fn(),
  advanceInterviewStream: vi.fn(),
  listDocuments: vi.fn(),
}));

const QUESTION = "On how many days did you commute?";

function step(answered: number): InterviewStep {
  return {
    status: "gathering",
    done: false,
    answered,
    pause: {
      type: "question",
      question_id: "commute.commuting_days",
      answer_type: "integer",
      text: { en: QUESTION },
    },
  } as unknown as InterviewStep;
}

const CONFIRMED = { id: "d1", state: "confirmed" } as unknown as LiveDocument;

async function renderInterview(documents: LiveDocument[], answered = 0) {
  const api = await import("@/features/cases/api");
  vi.mocked(api.advanceInterview).mockResolvedValue(step(answered));
  vi.mocked(api.listDocuments).mockResolvedValue(documents);
  render(
    <LocaleProvider>
      <LiveInterview caseId="case-1" />
    </LocaleProvider>,
  );
}

describe("documents before the first question", () => {
  it("offers them on a case that has neither documents nor answers", async () => {
    localStorage.clear();
    await renderInterview([]);

    await waitFor(() =>
      expect(screen.getByText("Have a payslip or any invoices?")).toBeInTheDocument(),
    );
    // The reason is stated, not implied: uploading first is less work, and nothing
    // about that is visible unless the screen says it.
    expect(screen.getByText(/takes its own question out of the interview/)).toBeInTheDocument();
    // And the tab does not go away - documents can still be added later.
    expect(screen.getByText(/at any time from the Documents tab/)).toBeInTheDocument();
  });

  it("does not offer them when the case already has a confirmed document", async () => {
    localStorage.clear();
    await renderInterview([CONFIRMED]);

    await waitFor(() => expect(screen.getByText(QUESTION)).toBeInTheDocument());
    expect(screen.queryByText("Have a payslip or any invoices?")).not.toBeInTheDocument();
  });

  it("does not interrupt an interview already under way", async () => {
    localStorage.clear();
    await renderInterview([], 7);

    await waitFor(() => expect(screen.getByText(QUESTION)).toBeInTheDocument());
    expect(screen.queryByText("Have a payslip or any invoices?")).not.toBeInTheDocument();
  });

  it("asks once and not on every refresh", async () => {
    localStorage.clear();
    const user = userEvent.setup();
    await renderInterview([]);
    await waitFor(() =>
      expect(screen.getByText("Have a payslip or any invoices?")).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: /start the interview/ }));
    await waitFor(() => expect(screen.getByText(QUESTION)).toBeInTheDocument());

    // A second visit to the same case: declining is remembered, so the shortcut does
    // not turn into a door the user has to close again every time.
    const again = await import("@/features/cases/api");
    vi.mocked(again.advanceInterview).mockResolvedValue(step(0));
    render(
      <LocaleProvider>
        <LiveInterview caseId="case-1" />
      </LocaleProvider>,
    );
    await waitFor(() => expect(screen.getAllByText(QUESTION).length).toBeGreaterThan(0));
    expect(screen.queryByText("Have a payslip or any invoices?")).not.toBeInTheDocument();
  });
});
