/**
 * What stands beside a figure on the live report: the document it came from and the
 * passage of law that authorises it.
 *
 * This is the promise the product is built on, and until now the richer block existed
 * only in a design fixture while the live report showed the amount, the form line and
 * the formula (#17). The two assertions worth having are that the quotation appears
 * for a figure that has one, and that it does *not* appear for one that has none -
 * training costs are a sum of receipts, and inventing a source for them would be the
 * failure this whole mechanism is meant to prevent.
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import type { LiveCaseDetail, LiveExpense } from "@/features/cases/api";
import { LiveReport } from "@/components/cases/live-report";
import { LocaleProvider } from "@/i18n/locale-provider";

const EXCERPT =
  "Sind die Anschaffungskosten höher als 800 €, müssen Sie diese auf die Jahre der " +
  "üblichen Nutzungsdauer verteilen.";

const DEPRECIATED: LiveExpense = {
  category: "arbeitsmittel",
  amount_eur: 128.21,
  form_line: "anlage_n 54-56",
  form: "anlage_n",
  form_lines: "54-56",
  trace: ["AfA over 13 years: 153.85 EUR/year, first year pro-rata 10/12 months"],
  documents: ["rechnung-hoffmann.jpg"],
  citations: [
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
};

/** A sum of receipts: no rate, no branch, and therefore nothing to quote. */
const SUMMED: LiveExpense = {
  category: "fortbildungskosten",
  amount_eur: 1200,
  form_line: "anlage_n 60",
  form: "anlage_n",
  form_lines: "60",
  trace: [],
  documents: [],
  citations: [],
};

function detail(expenses: LiveExpense[]): LiveCaseDetail {
  return {
    id: "case-1",
    tax_year: 2025,
    status: "reviewing",
    fields: {},
    unconfirmed_values: [],
    expenses,
    tax_positions: [],
    total_eur: expenses.reduce((sum, e) => sum + e.amount_eur, 0),
    pauschbetrag_eur: 1230,
    gaps: [],
    findings: [],
  } as unknown as LiveCaseDetail;
}

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/cases/case-1/report",
}));

vi.mock("@/features/cases/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/cases/api")>()),
  getCaseDetail: vi.fn(),
}));

async function renderReport(expenses: LiveExpense[]) {
  const { getCaseDetail } = await import("@/features/cases/api");
  vi.mocked(getCaseDetail).mockResolvedValue(detail(expenses));
  render(
    <LocaleProvider>
      <LiveReport caseId="case-1" />
    </LocaleProvider>,
  );
  await waitFor(() => expect(screen.getByText("Anlage N, Lines 54-56")).toBeInTheDocument());
}

describe("sources beside a figure", () => {
  it("quotes the provision the calculation actually applied", async () => {
    await renderReport([DEPRECIATED]);

    // Verbatim and in German: it is the text of the law, so a translated or shortened
    // version would be this product's wording presented as the Finanzamt's.
    expect(screen.getByText(EXCERPT)).toBeInTheDocument();
    expect(screen.getByText(/§ 7 Abs\. 1 EStG/)).toBeInTheDocument();
  });

  it("names the document the figure was read from", async () => {
    await renderReport([DEPRECIATED]);
    expect(screen.getByText(/rechnung-hoffmann\.jpg/)).toBeInTheDocument();
  });

  it("shows no source block for a figure that is a sum of receipts", async () => {
    const { getCaseDetail } = await import("@/features/cases/api");
    vi.mocked(getCaseDetail).mockResolvedValue(detail([SUMMED]));
    render(
      <LocaleProvider>
        <LiveReport caseId="case-1" />
      </LocaleProvider>,
    );
    await waitFor(() => expect(screen.getByText("Anlage N, Line 60")).toBeInTheDocument());

    expect(screen.queryByText("Official source")).not.toBeInTheDocument();
    expect(screen.queryByText(EXCERPT)).not.toBeInTheDocument();
  });
});
