import { describe, expect, it } from "vitest";

import de from "@/i18n/messages/de.json";
import en from "@/i18n/messages/en.json";
import ru from "@/i18n/messages/ru.json";
import tr from "@/i18n/messages/tr.json";

import { getTaxCase, listTaxCases } from "@/features/cases/case-api.stub";
import { messageKey } from "@/features/cases/format";

const CATALOGUES = { en, de, ru, tr } as Record<string, Record<string, unknown>>;

function lookup(catalogue: Record<string, unknown>, path: string): unknown {
  return path.split(".").reduce<unknown>((node, part) => {
    if (node && typeof node === "object" && part in node) {
      return (node as Record<string, unknown>)[part];
    }
    return undefined;
  }, catalogue);
}

describe("Tax Case fixture", () => {
  it("keeps the displayed total equal to the sum of Expenses", () => {
    const taxCase = getTaxCase("2025");
    const total = taxCase.expenses.reduce((sum, expense) => sum + expense.amountEur, 0);

    expect(total).toBeCloseTo(2109.9, 2);
    expect(taxCase.expenseTotalEur).toBeCloseTo(total, 2);
  });

  it("uses the 2025 Anlage N lines from the project domain model", () => {
    const taxCase = getTaxCase("2025");
    const lines = Object.fromEntries(
      taxCase.expenses.map((expense) => [expense.id, expense.formLine]),
    );

    expect(lines.homeoffice_tagespauschale).toBe("Zeile 58 (another workplace was available)");
    expect(lines.arbeitsmittel_1).toBe("Zeilen 54–56 (total in 56)");
    expect(lines.fortbildungskosten).toBe("Zeile 60");
    // Read from KB/Anlage_N_2025.pdf: the commute repeats in eight-line blocks, and
    // the total distance is Zeile 30 with the car share in 31 — not 31-33 together.
    expect(lines.entfernungspauschale).toContain("Zeilen 27–34");
  });

  it("keeps one Expense per purchased item, because AfA is per item", () => {
    const taxCase = getTaxCase("2025");
    const items = taxCase.expenses.filter((e) => e.category === "arbeitsmittel");

    expect(items).toHaveLength(3);
    expect(items.reduce((sum, e) => sum + e.amountEur, 0)).toBeCloseTo(178.2, 2);
  });

  it("only suggests categories the domain model can compute and place", () => {
    const taxCase = getTaxCase("2025");
    const known = [
      "entfernungspauschale",
      "homeoffice_tagespauschale",
      "arbeitsmittel",
      "telefon_internet",
      "fortbildungskosten",
      "umzugskosten",
      "bewerbungskosten",
    ];

    for (const candidate of taxCase.gapCandidates) {
      expect(known).toContain(candidate.category);
    }
  });

  it("exposes summaries through the future Case API boundary", () => {
    const summaries = listTaxCases();

    expect(summaries).toHaveLength(1);
    expect(summaries[0]).not.toHaveProperty("profile");
    expect(summaries[0]).not.toHaveProperty("expenses");
  });

  // The case screens are server-rendered on demand, so a missing message is not a
  // build error — it is a broken page. A field id qualified by its category holds a
  // dot, which next-intl reads as a namespace separator, so the id and its message
  // key are not the same string. That is exactly where this breaks silently.
  it("has every fixture id translated in all four locales", () => {
    const taxCase = getTaxCase("2025");
    const expected = [
      ...taxCase.profile.flatMap((field) => [
        `cases.fixture.profile.${messageKey(field.id)}.label`,
        `cases.fixture.profile.${messageKey(field.id)}.value`,
      ]),
      ...taxCase.answeredQuestions.flatMap((answer) => [
        `cases.fixture.answers.${messageKey(answer.id)}.question`,
        `cases.fixture.answers.${messageKey(answer.id)}.answer`,
      ]),
      ...taxCase.gapCandidates.map((gap) => `cases.fixture.gaps.${gap.id}.rationale`),
      ...taxCase.findings.map((finding) => `cases.fixture.findings.${finding.id}.title`),
    ];

    for (const [locale, catalogue] of Object.entries(CATALOGUES)) {
      const missing = expected.filter((path) => typeof lookup(catalogue, path) !== "string");
      expect(missing, `${locale} is missing ${missing.length} message(s)`).toEqual([]);
    }
  });

  it("names every case status the badges and the catalogues both know", () => {
    const statuses = ["gathering", "validating", "reviewing", "needs_user_input", "finalized"];

    for (const [locale, catalogue] of Object.entries(CATALOGUES)) {
      for (const status of statuses) {
        expect(
          lookup(catalogue, `cases.status.${status}`),
          `${locale} has no label for ${status}`,
        ).toBeTypeOf("string");
      }
    }
  });
});
