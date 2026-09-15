// The scope statement, straight from the build that serves it.
//
// Public on purpose: the landing page asks before anyone signs in, so this
// module carries no session and never imports the Supabase client. Everything
// it returns is an identifier, a number or an ISO date - the sentences live in
// the message catalogue, because the same statement has to be true in four
// languages.

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Mirrors api/routes/meta.py. A code the catalogue has no sentence for is shown
// as itself, which is ugly on purpose: an unexplained mode is a bug to fix, not
// a blank to hide.
export type ModeId = "chat" | "tax_case";

/**
 * What a mode leaves behind, one store at a time.
 *
 * Three fields, not one boolean. The browser's own chat history is the fourth
 * store and is deliberately not here: the backend cannot observe a localStorage,
 * so the page states that one from `lib/conversation-history.ts` instead.
 */
export interface DataScope {
  server: string;
  profile_memory: string;
  tracing: string;
}

export interface ModeScope {
  id: ModeId;
  available: boolean;
  reason: string;
  requires_account: boolean;
  storage: DataScope;
}

export interface FormScope {
  form: string;
  categories: string[];
  lines_verified: boolean;
}

export interface TaxYearScope {
  year: number;
  filing_due: string;
  filing_due_advised: string;
  voluntary_filing_until: string;
  forms: FormScope[];
}

export interface ScopeStatement {
  modes: ModeScope[];
  tax_years: TaxYearScope[];
  default_tax_year: number;
  limits: Record<string, number>;
  not_supported: string[];
}

export async function fetchScope(signal?: AbortSignal): Promise<ScopeStatement> {
  // no-store: a redeploy can change what is available, and a cached statement
  // that says otherwise is exactly the untruth this endpoint exists to prevent.
  const response = await fetch(`${API_URL}/api/v1/meta/scope`, {
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    throw new Error(`scope statement unavailable (${response.status})`);
  }
  return (await response.json()) as ScopeStatement;
}
