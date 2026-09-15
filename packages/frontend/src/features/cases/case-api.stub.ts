import { TAX_CASE_2025_FIXTURE, TAX_CASE_FIXTURES } from "./tax-case-2025.fixture";
import type { TaxCaseDto, TaxCaseSummaryDto } from "./types";

// This module is the temporary boundary for the future Case API. UI modules import
// these functions, not the fixture itself, so Supabase/FastAPI can replace the bodies
// without changing the screens.
export const CASE_BACKEND_MODE = "fixture" as const;

export function listTaxCases(): TaxCaseSummaryDto[] {
  return TAX_CASE_FIXTURES.map(({ profile: _profile, expenses: _expenses, ...taxCase }) => {
    const {
      gapCandidates: _gapCandidates,
      findings: _findings,
      documents: _documents,
      answeredQuestions: _answeredQuestions,
      pauschbetragEur: _pauschbetragEur,
      ...summary
    } = taxCase;
    return summary;
  });
}

export function getTaxCase(caseId: string): TaxCaseDto {
  return TAX_CASE_FIXTURES.find((taxCase) => taxCase.id === caseId) ?? TAX_CASE_2025_FIXTURE;
}

export async function requestMagicLink(_email: string): Promise<void> {
  // Keeps the loading state visible without pretending a real email was sent.
  await new Promise((resolve) => setTimeout(resolve, 650));
}
