/**
 * The final gate: three answers per proposed position, and a card that says who
 * produced the figure (#77, #89).
 *
 * The two things worth pinning are the ones that were wrong before. There was no way
 * to say "not sure" - the only expression of it was leaving the card alone, which
 * looks exactly like not having read it. And the origin of a figure reached the screen
 * as `Origin: deterministic_rule` in grey, which is information nobody can use: what a
 * person needs to know is that the arithmetic is not a model's, even when a model read
 * one of the numbers off their document.
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { InterviewStep, LiveTaxPosition } from "@/features/cases/api";
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
}));

const EXCERPT =
  "Sind die Anschaffungskosten höher als 800 €, müssen Sie diese auf die Jahre der " +
  "üblichen Nutzungsdauer verteilen.";

function position(overrides: Partial<LiveTaxPosition> = {}): LiveTaxPosition {
  return {
    position_id: "arbeitsmittel",
    category: "arbeitsmittel",
    assessment_status: "identified",
    user_decision: "pending",
    dependent_facts: [{ fact_id: "equipment.price_eur", version: "v1" }],
    source_refs: [
      {
        rule_id: "anlage-n:2025:arbeitsmittel:depreciation:v1",
        purpose: "calculation",
        source_id: "055-anleitung-anlage-n-2025",
        chunk_id: "055-anleitung-anlage-n-2025::012",
        title: "Anleitung zur Anlage N 2025",
        reference: "§ 7 Abs. 1 EStG",
        excerpt: EXCERPT,
      },
    ],
    calculator_version: "calculator:arbeitsmittel:v1",
    rule_version: "anlage-n:2025:arbeitsmittel:v1",
    proposed_amount: 128.21,
    origin: "deterministic_rule",
    missing_facts: [],
    provenance: [
      {
        role: "assessment",
        origin: "deterministic_rule",
        reference: "arbeitsmittel",
        version: "v1",
      },
    ],
    ...overrides,
  };
}

function step(positions: LiveTaxPosition[]): InterviewStep {
  return {
    done: false,
    status: "reviewing",
    pause: {
      type: "final_approval",
      expenses: [
        {
          category: "arbeitsmittel",
          amount_eur: 128.21,
          form_line: "anlage_n 54-56",
          form: "anlage_n",
          form_lines: "54-56",
          trace: ["AfA over 13 years"],
          documents: [],
          citations: [],
        },
      ],
      tax_positions: positions,
    },
  } as unknown as InterviewStep;
}

async function renderGate(positions: LiveTaxPosition[]) {
  const { advanceInterview } = await import("@/features/cases/api");
  vi.mocked(advanceInterview).mockResolvedValue(step(positions));
  render(
    <LocaleProvider>
      <LiveInterview caseId="case-1" />
    </LocaleProvider>,
  );
  await waitFor(() => expect(screen.getAllByText("Work equipment").length).toBeGreaterThan(0));
}

describe("deciding a proposed position", () => {
  it("asks the question the two answers answer, and offers both", async () => {
    await renderGate([position()]);

    // The question is the half that was missing: three buttons with no sentence above
    // them read as a switch that already has a value, not as a choice still owed.
    expect(screen.getByText(/Include this .* in your return\?/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add to the return" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Do not add" })).toBeInTheDocument();
  });

  it("shows an untouched position as waiting, not as answered", async () => {
    await renderGate([position()]);

    // Undecided is the state the card opens in, and it has to look like one. Before
    // this, "not sure" was a third button of equal weight and carried the default
    // styling, so an untouched card looked exactly like a decided one.
    expect(screen.getByText("Waiting for your decision")).toBeInTheDocument();
    expect(screen.getByText(/Choose one of the two/)).toBeInTheDocument();
    expect(screen.getByText("0 of 1 decided.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /I'm not sure/ })).not.toBeInTheDocument();
  });

  it("points at what is still open instead of going dead", async () => {
    const user = userEvent.setup();
    await renderGate([position()]);

    // Not disabled: a grey button states a rule and offers no way to satisfy it. This
    // one takes the user to the position still waiting and says how many there are.
    const finish = screen.getByRole("button", { name: /Show what still needs a decision/ });
    expect(finish).toBeEnabled();
    await user.click(finish);
    expect(screen.getByText(/1 position is still waiting/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add to the return" }));
    expect(screen.getByText("In the return")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Approve/ })).toBeEnabled();
  });

  it("re-opens the question when the user goes back to not sure", async () => {
    const user = userEvent.setup();
    await renderGate([position()]);

    await user.click(screen.getByRole("button", { name: "Add to the return" }));
    expect(screen.getByRole("button", { name: /Approve/ })).toBeEnabled();

    // Taking the answer back is offered only once there is an answer to take back.
    await user.click(screen.getByRole("button", { name: /I'm not sure/ }));
    expect(screen.getByText("Waiting for your decision")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Approve/ }),
    ).not.toBeInTheDocument();
  });

  it("says the arithmetic is not the model's", async () => {
    await renderGate([position()]);
    expect(screen.getByText("Calculated from the answers you confirmed.")).toBeInTheDocument();
  });

  it("separates a value the model read from a figure the model proposed", async () => {
    // A model transcribing a number off a payslip is not a model proposing a
    // deduction, and the card has to keep the two apart (#89).
    await renderGate([
      position({
        provenance: [
          {
            role: "assessment",
            origin: "deterministic_rule",
            reference: "arbeitsmittel",
            version: "v1",
          },
          {
            role: "extraction",
            origin: "ai_inference",
            reference: "document:doc-1",
            version: null,
          },
          {
            role: "confirmation",
            origin: "user_input",
            reference: "document:doc-1",
            version: null,
          },
        ],
      }),
    ]);

    expect(screen.getByText(/Calculated from the answers you confirmed/)).toBeInTheDocument();
    expect(
      screen.getByText(/read from a document by the AI and confirmed by you/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Proposed by the AI/)).not.toBeInTheDocument();
  });

  it("shows the provision behind the figure when asked why", async () => {
    const user = userEvent.setup();
    await renderGate([position()]);

    await user.click(screen.getByText("Why this is proposed"));
    expect(screen.getByText(EXCERPT)).toBeInTheDocument();
    expect(screen.getByText("§ 7 Abs. 1 EStG")).toBeInTheDocument();
  });
});
