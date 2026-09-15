// The live Case API: FastAPI on the other side, the Supabase session's token in
// every request. The stub (case-api.stub.ts) remains the fallback the screens use
// when no Supabase project is configured, so this module never guesses — a missing
// session here is an error, not a mode.

import { supabase } from "@/lib/supabase";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    detail: string,
  ) {
    super(detail);
  }
}

export type LiveCaseSummary = {
  id: string;
  tax_year: number;
  status: string;
};

export type LiveFieldValue = {
  value: unknown;
  provenance: "answer" | "document" | "assumed" | "remembered";
  confirmed: boolean;
  // Set only on a value somebody changed by hand. Without it the screen would show
  // the corrected number as though nobody had touched it, and the trace could not
  // say a figure was changed after a model read it off a document (#28).
  superseded_value?: unknown;
  superseded_provenance?: string | null;
};

export type LiveExpense = {
  category: string;
  amount_eur: number;
  // The exact identifier, kept for exports a machine reads: "anlage_n 54-56".
  form_line: string;
  // The same thing split, so the interface can name the form in the reader's
  // language instead of printing an internal identifier at them (#56).
  form: string;
  form_lines: string;
  trace: string[];
  // The documents behind the figure, by id - a list because three invoices in one
  // category are three documents. Empty for a figure built from interview answers.
  documents: string[];
  // The official passages behind the figure, one per branch of the calculator that
  // actually ran, resolved when the position was assessed. Empty for a category that
  // is a sum of receipts rather than a rate - training costs have no rule to quote.
  citations: RuleCitation[];
};

export type RuleCitation = {
  rule_id: string;
  purpose: "eligibility" | "calculation" | "placement";
  source_id: string;
  chunk_id: string;
  title: string;
  // How a German reader names the provision: "§ 9 Abs. 1 Satz 3 Nr. 4 EStG".
  reference: string;
  // Verbatim, and in German. It is a quotation from the law, so it is not translated
  // and not paraphrased; the plain-language explanation is the formula above it.
  excerpt: string;
};

export type LiveTaxPosition = {
  position_id: string;
  category: string;
  assessment_status: "identified" | "criteria_not_met" | "unclear";
  user_decision: "pending" | "accepted" | "rejected" | "needs_reconfirmation";
  dependent_facts: Array<{ fact_id: string; version: string }>;
  // The official passages behind the figure, resolved when the position was assessed.
  source_refs: RuleCitation[];
  calculator_version: string | null;
  rule_version: string | null;
  proposed_amount: number | null;
  // `ai_inference` is a value a model read out of a document, as distinct from
  // `ai_suggestion`, which is a model proposing something of its own.
  origin: Origin;
  missing_facts: string[];
  // One entry per thing that contributed, so the screen can say who did what rather
  // than printing one label over the whole position. A document-backed position
  // carries two entries per document - the model transcribed the value, the person
  // confirmed it - and collapsing them would either overstate the machine's part or
  // hide it.
  provenance: Array<{ role: string; origin: Origin; reference: string; version: string | null }>;
};

export type Origin =
  "user_input" | "deterministic_rule" | "retrieved_source" | "ai_suggestion" | "ai_inference";

export type LiveCaseDetail = LiveCaseSummary & {
  fields: Record<string, LiveFieldValue>;
  // Assumptions and values carried over from an earlier year: both wait for the user.
  unconfirmed_values: string[];
  expenses: LiveExpense[];
  tax_positions: LiveTaxPosition[];
  total_eur: number;
  pauschbetrag_eur: number;
  gaps: Array<{ category: string; rationale: string }>;
  // What the Reviewer raised, worst first. Empty both when the review found nothing
  // and when it has not run yet — the case status tells the two apart.
  findings: Array<{
    severity: "blocking" | "warning" | "suggestion";
    title: string;
    reasoning: string;
    category: string;
    resolution: "open" | "fixed" | "dismissed";
  }>;
  // Whether the last review ran with its own model. Null before any review has run;
  // false means it fell back to deterministic rules, which is not a second opinion.
  review_from_model: boolean | null;
  review_note: string;
};

export type InterviewPause = {
  type: "question" | "confirm_stop" | "findings" | "final_approval";
  // question
  question_id?: string;
  field?: string;
  // The expense category a question belongs to, null for a profile question. The
  // agent moves between topics on purpose, so the card names the topic it is in.
  category?: string | null;
  answer_type?: string;
  options?: string[];
  minimum?: number | null;
  maximum?: number | null;
  required?: boolean;
  text?: Record<string, string>;
  // Which purchase of a repeating category the question is about. 0 for everything
  // else, so the card only says "Purchase 2" when there really is a second one (#35).
  item_index?: number;
  rationale?: string;
  // confirm_stop
  reason?: string;
  escalated?: boolean;
  // findings / final_approval
  findings?: Array<{ severity: string; title: string; reasoning: string }>;
  expenses?: LiveExpense[];
  tax_positions?: LiveTaxPosition[];
  // confirm_stop: values this person gave in an earlier year, offered for confirmation
  // now that the gates are answered and it is known whether they still apply.
  carried_over?: Array<{
    key: string;
    value: unknown;
    source: string;
    text: Record<string, string>;
    answer_type: string;
  }>;
  // confirm_stop: deductions the profile points at that the case does not hold
  gaps?: Array<{
    category: string;
    rationale: string;
    citation_title?: string;
    citation_quote?: string;
  }>;
};

export type InterviewStep = {
  status: string;
  pause: InterviewPause | null;
  done: boolean;
  // Answered questions, counted in the tables rather than in this browser, so a
  // refresh shows the truth instead of zero (#53).
  answered: number;
  // Present only when the backend runs with DEBUG=true; feeds the developer panel.
  debug?: import("@/components/cases/agent-graph-panel").AgentDebug | null;
};

async function token(): Promise<string> {
  if (!supabase) throw new ApiError(0, "Supabase is not configured");
  const { data } = await supabase.auth.getSession();
  const accessToken = data.session?.access_token;
  if (!accessToken) throw new ApiError(401, "not signed in");
  return accessToken;
}

/**
 * The locale the backend should write its labels in.
 *
 * Read from storage rather than from React, because this module is not a component
 * and the value it needs is the one `LocaleProvider` persisted. A Tax Case does not
 * carry a locale yet - that is issue #47 - so the header is how the backend learns
 * which language the person in front of the screen reads.
 */
function uiLocale(): string {
  try {
    return localStorage.getItem("ui-locale") || navigator.language || "en";
  } catch {
    // Storage can be unavailable (private windows, blocked site data); English is
    // what the backend falls back to anyway.
    return "en";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "Accept-Language": uiLocale(),
      Authorization: `Bearer ${await token()}`,
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      // a non-JSON error body keeps the status text
    }
    throw new ApiError(response.status, detail);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

export function listCases(): Promise<LiveCaseSummary[]> {
  return request("/api/v1/cases");
}

export function createCase(taxYear: number): Promise<LiveCaseSummary> {
  return request("/api/v1/cases", {
    method: "POST",
    body: JSON.stringify({ tax_year: taxYear }),
  });
}

export function getCaseDetail(caseId: string): Promise<LiveCaseDetail> {
  return request(`/api/v1/cases/${caseId}`);
}

export function deleteCase(caseId: string): Promise<void> {
  return request(`/api/v1/cases/${caseId}`, { method: "DELETE" });
}

// Lifts the read-only lock a finished case carries, so a decision made at the end
// can be taken back. Safe to call twice: a case that is not finalized comes back
// unchanged rather than as an error.
export function reopenCase(caseId: string): Promise<LiveCaseSummary> {
  return request(`/api/v1/cases/${caseId}/reopen`, { method: "POST" });
}

// Every case this user has. Resolves only when all of them are gone: a partial
// failure comes back as a 500 naming how many are left, and repeating it is safe.
export function deleteAllCases(): Promise<void> {
  return request("/api/v1/cases", { method: "DELETE" });
}

// What the system remembers about the person between tax years - deliberately not
// part of deleting a case, and not implied by it (ADR 0011). Succeeds with nothing
// remembered: the caller asked for there to be nothing, and there is nothing.
export function forgetProfileMemory(): Promise<void> {
  return request("/api/v1/profile/memory", { method: "DELETE" });
}

// One call, one pause: resume undefined reconnects to the pending pause without
// advancing (refreshing the page must never eat a question), any other value
// answers it.
export function advanceInterview(caseId: string, resume?: unknown): Promise<InterviewStep> {
  return request(`/api/v1/cases/${caseId}/interview`, {
    method: "POST",
    body: JSON.stringify({ resume: resume ?? null }),
  });
}

// The case drawn onto the official Anlage N. Not `request`: the body is a PDF, not
// JSON, and the interesting part of the response is a header — how many figures the
// form had no single unambiguous box for, which the caller has to show rather than
// let the user assume the sheet is complete.
// --- Documents -----------------------------------------------------------------
//
// The upload sends the file as the **raw request body**, not as multipart form data.
// That is the backend's requirement rather than a client preference: Starlette's
// multipart parser spools any part over 1 MiB into a temporary file on disk, and a
// photographed payslip is 2 to 5 MB (ADR 0004, packages/backend/api/routes/documents.py).

export type DocumentKind = "lohnsteuerbescheinigung" | "rechnung";

export type ProposedValue = {
  key: string;
  value: unknown;
  /** What the value reads as, from the backend's Question catalogue. */
  label: string;
  /** Which one it is where a category can hold several, counted from 1; null otherwise. */
  item: number | null;
};

export type LiveDocument = {
  id: string;
  file_name: string;
  kind: DocumentKind | null;
  state: "reading" | "awaiting_confirmation" | "confirmed" | "discarded" | "failed";
  proposed: ProposedValue[];
  questions: string[];
  disagreements: string[];
  category: string | null;
  category_reason: string;
  contradiction: string | null;
  category_choices: string[];
  /** Which model read the document - not always the configured one. */
  read_by: string | null;
  // What the two extraction passes cost, once the document is stored. Null while it
  // is still an open intake run, and null for a model with no price on file - which
  // is a gap and not a zero (#39).
  read_cost_usd: number | null;
  read_tokens: number | null;
  failure_code: string | null;
  failure_detail: string | null;
};

export async function listDocuments(caseId: string): Promise<LiveDocument[]> {
  return request<LiveDocument[]>(`/api/v1/cases/${caseId}/documents`);
}

export async function uploadDocument(
  caseId: string,
  file: File,
  kind: DocumentKind,
  // One key per attempt, not per file: a retry after a dropped connection must be
  // the same key, or it becomes a second document and two more paid model calls.
  idempotencyKey: string,
): Promise<LiveDocument> {
  const query = new URLSearchParams({ kind, file_name: file.name });
  const response = await fetch(`${API_URL}/api/v1/cases/${caseId}/documents?${query.toString()}`, {
    method: "POST",
    body: file,
    headers: {
      "Content-Type": file.type || "application/octet-stream",
      "Accept-Language": uiLocale(),
      "Idempotency-Key": idempotencyKey,
      Authorization: `Bearer ${await token()}`,
    },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      // a non-JSON error body keeps the status text
    }
    throw new ApiError(response.status, detail);
  }
  return response.json();
}

export async function confirmDocument(
  caseId: string,
  documentId: string,
  values: Record<string, unknown>,
  category?: string | null,
): Promise<LiveDocument> {
  return request<LiveDocument>(`/api/v1/cases/${caseId}/documents/${documentId}/confirm`, {
    method: "POST",
    body: JSON.stringify({ values, category: category ?? null }),
  });
}

/**
 * Map a document again under the category the user picked.
 *
 * A separate call rather than a field on the confirmation, because the values an
 * invoice yields are keyed by category - choosing one asks the backend for another
 * proposal, and the answer carries the new keys to confirm.
 */
export async function setDocumentCategory(
  caseId: string,
  documentId: string,
  category: string,
): Promise<LiveDocument> {
  return request<LiveDocument>(`/api/v1/cases/${caseId}/documents/${documentId}/category`, {
    method: "POST",
    body: JSON.stringify({ category }),
  });
}

export async function discardDocument(caseId: string, documentId: string): Promise<LiveDocument> {
  return request<LiveDocument>(`/api/v1/cases/${caseId}/documents/${documentId}/discard`, {
    method: "POST",
  });
}

export async function downloadAnlageN(
  caseId: string,
): Promise<{ blob: Blob; filename: string; unplaced: number; kind: "draft" | "final" }> {
  const response = await fetch(`${API_URL}/api/v1/cases/${caseId}/anlage-n.pdf`, {
    headers: { Authorization: `Bearer ${await token()}` },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      // a non-JSON error body keeps the status text
    }
    throw new ApiError(response.status, detail);
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const named = /filename="([^"]+)"/.exec(disposition);
  return {
    blob: await response.blob(),
    filename: named?.[1] ?? `anlage-n-${caseId}.pdf`,
    unplaced: Number(response.headers.get("X-Unplaced-Count") ?? 0),
    // "final" only for an approved case whose every figure fit on the blank; the
    // page itself carries the matching banner, and this is so the screen agrees
    // with the file the user just saved (#30).
    kind: response.headers.get("X-Export-Kind") === "final" ? "final" : "draft",
  };
}

// Undo the last answer and get its question back. Not an advance: nothing is
// resumed, the run is replayed from the checkpoint that question was asked at.
// A 409 means there is nothing earlier to go back to — the first question.
export function stepBackInterview(caseId: string): Promise<InterviewStep> {
  return request(`/api/v1/cases/${caseId}/interview/back`, { method: "POST" });
}

// The same advance over SSE: `onNode` fires as the graph crosses each node, so
// the developer panel lights up in real time instead of reconstructing the path.
// Any transport hiccup falls back to the plain endpoint — same generator on the
// backend, so nothing can be lost by falling back.
export async function advanceInterviewStream(
  caseId: string,
  resume: unknown,
  onNode: (node: string) => void,
): Promise<InterviewStep> {
  try {
    const response = await fetch(`${API_URL}/api/v1/cases/${caseId}/interview/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${await token()}`,
      },
      body: JSON.stringify({ resume: resume ?? null }),
    });
    if (!response.ok || !response.body) throw new ApiError(response.status, response.statusText);

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let result: InterviewStep | null = null;

    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const event = JSON.parse(line.slice(6));
        if (event.type === "node") onNode(event.node);
        else if (event.type === "error") throw new ApiError(event.status ?? 0, event.detail);
        else if (event.type === "result") result = event as InterviewStep;
      }
    }
    if (!result) throw new ApiError(0, "stream ended without a result");
    return result;
  } catch (exc) {
    if (
      exc instanceof ApiError &&
      (exc.status === 401 || exc.status === 409 || exc.status === 422 || exc.status === 429)
    ) {
      throw exc; // real refusals surface; only transport problems fall back
    }
    return advanceInterview(caseId, resume);
  }
}

/**
 * Correct one fact in place, without walking back through the interview.
 *
 * The editable unit is the fact and never the computed total: a figure is a read over
 * the facts, so editing the rendered number would leave the trace claiming a formula
 * produced something it did not (#12). The whole case comes back recalculated.
 */
export function correctField(
  caseId: string,
  key: string,
  value: unknown,
  itemIndex = 0,
): Promise<LiveCaseDetail> {
  return request(`/api/v1/cases/${caseId}/fields/${encodeURIComponent(key)}`, {
    method: "PATCH",
    body: JSON.stringify({ value, item_index: itemIndex }),
  });
}

/** Remove one purchase from a repeating category. Item 0 is the category itself. */
export function removeItem(
  caseId: string,
  category: string,
  itemIndex: number,
): Promise<LiveCaseDetail> {
  return request(`/api/v1/cases/${caseId}/items/${category}/${itemIndex}`, {
    method: "DELETE",
  });
}
