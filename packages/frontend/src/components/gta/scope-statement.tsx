"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { CheckCircle2, CircleSlash, Loader2, MinusCircle, RefreshCw } from "lucide-react";

import { useScope } from "@/hooks/use-scope";
import type { ModeScope, ScopeStatement as Scope, TaxYearScope } from "@/features/meta/api";
import { MAX_CONVERSATIONS, MAX_HISTORY_TURNS } from "@/lib/conversation-history";

/**
 * The scope statement, rendered from what the backend says it is.
 *
 * Nothing here is written twice. Every year, form, limit and refusal comes from
 * `/api/v1/meta/scope`; the catalogue supplies only the sentence around it. So a
 * year added to `domain/tax_years.py` appears on this page without anyone
 * editing it, and a claim cannot outlive the build that made it true.
 *
 * Identifiers the catalogue has no wording for are shown as themselves. That
 * looks wrong because it is: an unexplained id means the backend grew something
 * the four languages have not been told about yet.
 */

type Translate = ReturnType<typeof useTranslations>;

function label(t: Translate, key: string, fallback: string): string {
  return t.has(key) ? t(key) : fallback;
}

export function ScopeStatement() {
  const t = useTranslations("scope");
  const { status, scope, retry } = useScope();

  if (status === "loading") {
    return (
      <div className="flex items-center gap-2 py-16 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("loading")}
      </div>
    );
  }

  if (status === "unavailable") {
    // No cached copy, deliberately. A statement that cannot be fetched is a
    // statement nobody can vouch for, and a stale one is the failure this page
    // was built to prevent.
    return (
      <div className="rounded-2xl border border-border bg-surface p-6">
        <h2 className="text-[15px] font-semibold text-foreground">{t("unavailableTitle")}</h2>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{t("unavailableBody")}</p>
        <button
          type="button"
          onClick={retry}
          className="mt-4 inline-flex items-center gap-2 rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-foreground transition hover:border-border-strong"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          {t("retry")}
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-12">
      <Modes scope={scope} t={t} />
      <Years scope={scope} t={t} />
      <Limits scope={scope} t={t} />
      <NotSupported scope={scope} t={t} />
    </div>
  );
}

function Modes({ scope, t }: { scope: Scope; t: Translate }) {
  return (
    <section>
      <SectionTitle>{t("modesTitle")}</SectionTitle>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        {scope.modes.map((mode) => (
          <ModeCard key={mode.id} mode={mode} t={t} />
        ))}
      </div>
    </section>
  );
}

function ModeCard({ mode, t }: { mode: ModeScope; t: Translate }) {
  const title = label(t, `mode.${mode.id}.title`, mode.id);
  const body = label(t, `mode.${mode.id}.body`, "");

  return (
    <div className="rounded-2xl border border-border bg-surface p-6">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-[15px] font-semibold text-foreground">{title}</h3>
        <Badge ok={mode.available}>{mode.available ? t("open") : t("closed")}</Badge>
      </div>
      {body ? <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{body}</p> : null}

      {/* The reason rides along even on an open mode: `schema_not_checked` means
          the instance is still starting, which a visitor deserves to know before
          the first Tax Case rather than after it fails. */}
      {mode.reason ? (
        <p className="mt-3 text-sm text-muted-foreground">
          {label(t, `reason.${mode.reason}`, mode.reason)}
        </p>
      ) : null}

      <ul className="mt-4 space-y-1.5 text-[13px] text-muted-foreground">
        <li>{mode.requires_account ? t("accountNeeded") : t("noAccount")}</li>
        <li>{label(t, `storage.server.${mode.storage.server}`, mode.storage.server)}</li>
        {/* The browser's history is this side's fact, so this side states it, with
            the numbers read from the module that enforces them rather than typed
            into four catalogues. The backend cannot see a localStorage and the page
            used to render its silence as "keeps nothing about you". */}
        {mode.id === "chat" ? (
          <li>
            {t("storage.browser", {
              conversations: MAX_CONVERSATIONS,
              turns: MAX_HISTORY_TURNS,
            })}
          </li>
        ) : null}
        <li>
          {label(
            t,
            `storage.profileMemory.${mode.storage.profile_memory}`,
            mode.storage.profile_memory,
          )}
        </li>
        <li>{label(t, `storage.tracing.${mode.storage.tracing}`, mode.storage.tracing)}</li>
      </ul>
    </div>
  );
}

function Years({ scope, t }: { scope: Scope; t: Translate }) {
  return (
    <section>
      <SectionTitle>{t("yearsTitle")}</SectionTitle>
      <p className="mt-2 text-sm text-muted-foreground">
        {t("defaultYear", { year: scope.default_tax_year })}
      </p>
      <div className="mt-4 space-y-4">
        {scope.tax_years.map((year) => (
          <YearCard key={year.year} year={year} t={t} />
        ))}
      </div>
      {/* Three dates with three labels are three claims a visitor can act on
          wrongly: the first one only binds somebody obliged to file, the second
          can be pulled forward by the tax office, and the third is the voluntary
          window. The paragraph says which is which. */}
      <p className="mt-4 text-[13px] leading-relaxed text-muted-foreground">{t("deadlineNote")}</p>
    </section>
  );
}

function YearCard({ year, t }: { year: TaxYearScope; t: Translate }) {
  return (
    <div className="rounded-2xl border border-border bg-surface p-6">
      <h3 className="text-[15px] font-semibold text-foreground">{year.year}</h3>

      <dl className="mt-4 grid gap-3 text-[13px] sm:grid-cols-3">
        <Fact term={t("filingDue")} value={year.filing_due} />
        <Fact term={t("filingDueAdvised")} value={year.filing_due_advised} />
        <Fact term={t("voluntaryUntil")} value={year.voluntary_filing_until} />
      </dl>

      <div className="mt-5 space-y-4 border-t border-border pt-4">
        {year.forms.map((form) => (
          <div key={form.form}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[13px] font-medium text-foreground">
                {label(t, `form.${form.form}`, form.form)}
              </span>
              {!form.lines_verified ? (
                <span className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground">
                  {t("linesUnverified")}
                </span>
              ) : null}
            </div>
            <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">
              {form.categories.map((c) => label(t, `category.${c}`, c)).join(" · ")}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

function Limits({ scope, t }: { scope: Scope; t: Translate }) {
  const entries = Object.entries(scope.limits);

  return (
    <section>
      <SectionTitle>{t("limitsTitle")}</SectionTitle>
      <p className="mt-2 text-sm text-muted-foreground">{t("limitsIntro")}</p>
      <dl className="mt-4 grid gap-3 text-[13px] sm:grid-cols-2">
        {entries.map(([name, value]) => (
          <Fact
            key={name}
            term={label(t, `limit.${name}`, name)}
            // Zero is not "none allowed" - it is how the backend spells a limit
            // that is switched off, and printing "0" would say the opposite.
            value={value === 0 ? t("limitOff") : String(value)}
          />
        ))}
      </dl>
    </section>
  );
}

function NotSupported({ scope, t }: { scope: Scope; t: Translate }) {
  return (
    <section>
      <SectionTitle>{t("notSupportedTitle")}</SectionTitle>
      <p className="mt-2 text-sm text-muted-foreground">{t("notSupportedIntro")}</p>
      <ul className="mt-4 space-y-2">
        {scope.not_supported.map((id) => (
          <li key={id} className="flex items-start gap-2 text-[13px] text-muted-foreground">
            <MinusCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
            {label(t, `notSupported.${id}`, id)}
          </li>
        ))}
      </ul>
    </section>
  );
}

function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <h2 className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
      {children}
    </h2>
  );
}

function Fact({ term, value }: { term: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground">{term}</dt>
      <dd className="mt-0.5 font-medium text-foreground">{value}</dd>
    </div>
  );
}

function Badge({ ok, children }: { ok: boolean; children: ReactNode }) {
  const Icon = ok ? CheckCircle2 : CircleSlash;
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium ${
        ok ? "border-border text-foreground" : "border-border text-muted-foreground"
      }`}
    >
      <Icon className="h-3 w-3" strokeWidth={2} />
      {children}
    </span>
  );
}
