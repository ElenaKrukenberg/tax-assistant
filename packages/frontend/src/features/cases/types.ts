// The five states of the LangGraph case model, named as docs/AGENT_ARCHITECTURE.md
// names them so that a screen and the backend never disagree about which one it is.
export type TaxCaseStatus =
  "gathering" | "validating" | "reviewing" | "needs_user_input" | "finalized";

// The seven Werbungskosten categories of domain/fields.py, in the same order.
export type ExpenseCategory =
  | "entfernungspauschale"
  | "homeoffice_tagespauschale"
  | "arbeitsmittel"
  | "telefon_internet"
  | "fortbildungskosten"
  | "umzugskosten"
  | "bewerbungskosten";

export type ExpenseStatus = "draft" | "confirmed" | "flagged";

export type Provenance = "answer" | "document" | "assumed" | "remembered";

// A Finding is the Reviewer's judgement, a ValidationIssue is a rule being broken.
// The two vocabularies stay separate on purpose: collapsing them would hide which
// of the two a screen is showing. See CONTEXT.md under Finding.
export type FindingSeverity = "blocking" | "warning" | "suggestion";

export type ValidationSeverity = "error" | "warning" | "info";

export type DocumentState = "uploading" | "reading" | "awaiting" | "confirmed";

export type EvidenceDto = {
  label: string;
  provenance: Provenance;
};

export type OfficialSourceDto = {
  title: string;
  reference: string;
  excerpt: string;
};

export type ExpenseDto = {
  id: string;
  category: ExpenseCategory;
  categoryLabel: string;
  amountEur: number;
  evidence: EvidenceDto[];
  formLine: string;
  status: ExpenseStatus;
  formula: string;
  substitutedValues: string;
  officialSource: OfficialSourceDto;
};

export type ProfileFieldDto = {
  id: string;
  value: string;
  provenance: Provenance;
  provenanceLabel: string;
};

export type GapCandidateDto = {
  id: string;
  category: ExpenseCategory;
  categoryLabel: string;
  officialSource: OfficialSourceDto;
};

export type FindingDto = {
  id: string;
  severity: FindingSeverity;
  affectedExpenseId: string;
};

// No confidence score. A vision model can name a number but it is not calibrated,
// and a reader takes 0.97 as a measurement. Every extracted field is presented as
// needing a look instead — see docs/DECISIONS.md.
export type ExtractedFieldDto = {
  id: string;
  value: string;
};

export type UploadedDocumentDto = {
  id: string;
  name: string;
  sizeLabel: string;
  state: DocumentState;
  progress?: number;
  readingStep?: string;
  fields?: ExtractedFieldDto[];
  confirmedSummary?: string;
};

export type AnsweredQuestionDto = {
  id: string;
};

export type TaxCaseSummaryDto = {
  id: string;
  taxYear: number;
  status: TaxCaseStatus;
  progress: number;
  expenseTotalEur: number;
  lastTouchedIso: string;
};

export type TaxCaseDto = TaxCaseSummaryDto & {
  profile: ProfileFieldDto[];
  expenses: ExpenseDto[];
  gapCandidates: GapCandidateDto[];
  findings: FindingDto[];
  documents: UploadedDocumentDto[];
  answeredQuestions: AnsweredQuestionDto[];
  pauschbetragEur: number;
};
