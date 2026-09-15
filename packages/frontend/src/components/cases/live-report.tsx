"use client";

// The deliverable, on live data: every figure with its calculation, its form
// line and its provenance — the file the user used to assemble by hand each
// year, which is the product's founding promise (docs/PRODUCT_VISION.md).
//
// Rendered as a page and printed by the browser (ADR: Markdown over DOCX); the
// download button hands over the same content as a Markdown file. Benefits that
// belong to the Hauptvordruck are a separate block that says exactly that,
// never a row among Anlage N figures (DECISIONS.md: named, not computed).

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Download, FileText, MessagesSquare, Printer } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { GermanTerm } from "@/components/cases/german-term";
import { ReopenButton } from "@/components/cases/reopen-button";
import { EmptyState } from "@/components/cases/states";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ApiError,
  type LiveCaseDetail,
  downloadAnlageN,
  getCaseDetail,
} from "@/features/cases/api";
import { formLabel, formatEur } from "@/features/cases/format";
import { useLocale } from "@/i18n/locale-provider";

function saveBlob(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function downloadMarkdown(filename: string, content: string) {
  saveBlob(filename, new Blob([content], { type: "text/markdown;charset=utf-8" }));
}

export function LiveReport({ caseId }: { caseId: string }) {
  const t = useTranslations("cases");
  const { locale } = useLocale();
  const router = useRouter();
  const [detail, setDetail] = useState<LiveCaseDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [formState, setFormState] = useState<
    | { kind: "idle" }
    | { kind: "working" }
    | { kind: "note"; unplaced: number; export: "draft" | "final" }
    | { kind: "failed"; message: string }
  >({ kind: "idle" });

  async function getAnlageN() {
    setFormState({ kind: "working" });
    try {
      const { blob, filename, unplaced, kind } = await downloadAnlageN(caseId);
      saveBlob(filename, blob);
      setFormState({ kind: "note", unplaced, export: kind });
    } catch (exc) {
      setFormState({
        kind: "failed",
        message: exc instanceof Error ? exc.message : String(exc),
      });
    }
  }

  useEffect(() => {
    getCaseDetail(caseId)
      .then(setDetail)
      .catch((exc) => {
        if (exc instanceof ApiError && exc.status === 401) {
          router.replace("/login");
          return;
        }
        setError(exc instanceof Error ? exc.message : String(exc));
      });
  }, [caseId, router]);

  if (error) {
    return (
      <p
        role="alert"
        className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm"
      >
        {error}
      </p>
    );
  }
  if (!detail) {
    return <Skeleton className="h-64 w-full rounded-xl" />;
  }

  const formatLocale = locale as Parameters<typeof formatEur>[1];
  const itemisedWins = detail.total_eur > detail.pauschbetrag_eur;
  const benefit = detail.fields["benefit_amount_eur"]?.value;
  const draft = detail.status !== "finalized";

  if (detail.expenses.length === 0) {
    return (
      <EmptyState
        title={t("report.emptyTitle")}
        description={t("report.emptyBody")}
        action={
          <Button asChild>
            <Link href={`/cases/${caseId}/interview`}>
              <MessagesSquare className="size-4" />
              {t("overview.startInterview")}
            </Link>
          </Button>
        }
      />
    );
  }

  function markdown(): string {
    const d = detail!;
    const rows = d.expenses
      .map((expense) => {
        const name = t.has(`categories.${expense.category}`)
          ? t(`categories.${expense.category}`)
          : expense.category;
        const official = t.has(`categoriesOfficial.${expense.category}`)
          ? t(`categoriesOfficial.${expense.category}`)
          : "";
        // The file people keep has to be usable in front of the Finanzamt, so it
        // carries the German name too - unless it is already the German one.
        const label = official && official !== name ? `${name} (${official})` : name;
        const trace = expense.trace.map((line) => `  - ${line}`).join("\n");
        // The export carries what the screen carries. A Markdown file with the figure
        // and the formula but not the document or the law would be a weaker claim
        // than the page it came from, and it is the copy people keep.
        const evidence = expense.documents
          .map((document) => `  - ${t("report.fromDocument", { document })}`)
          .join("\n");
        const sources = expense.citations
          .map((c) => `  - ${c.reference} (${c.title}):\n    > ${c.excerpt}`)
          .join("\n");
        return (
          `## ${label}\n\n` +
          `- ${t("report.amount")}: ${formatEur(expense.amount_eur, formatLocale)}\n` +
          `- ${t("report.formLine")}: ${formLabel(expense, t)}\n` +
          `${trace ? `- ${t("report.formula")}:\n${trace}\n` : ""}` +
          `${evidence ? `- ${t("report.evidence")}:\n${evidence}\n` : ""}` +
          `${sources ? `- ${t("report.officialSource")}:\n${sources}\n` : ""}`
        );
      })
      .join("\n\n");
    const benefitBlock =
      benefit != null
        ? `\n\n## ${t("report.benefitTitle")}\n\n${t("report.benefitBody", {
            amount: formatEur(Number(benefit), formatLocale),
          })}`
        : "";
    return `# ${t("report.title")}\n\n${t("common.taxYear")}: ${d.tax_year}${draft ? ` (${t("report.draft")})` : ""}\n\n${t(
      "report.totalLine",
      {
        total: formatEur(d.total_eur, formatLocale),
        allowance: formatEur(d.pauschbetrag_eur, formatLocale),
      },
    )}\n\n${rows}${benefitBlock}\n\n---\n\n${t("report.disclaimer")}\n`;
  }

  return (
    <article className="print-plain mx-auto w-full max-w-3xl">
      {draft ? (
        <div className="print-hide mb-6 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-sm">
          {t("report.draftNotice")}
        </div>
      ) : null}

      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl leading-tight">{t("report.title")}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("common.taxYear")} {detail.tax_year}, Anlage N
          </p>
        </div>
        <div className="print-hide flex gap-2">
          <Button variant="outline" onClick={() => window.print()}>
            <Printer className="size-4" />
            {t("report.print")}
          </Button>
          <Button
            variant="outline"
            onClick={() => downloadMarkdown(`tax-case-${detail.tax_year}.md`, markdown())}
          >
            <Download className="size-4" />
            {t("report.markdown")}
          </Button>
          <Button onClick={() => void getAnlageN()} disabled={formState.kind === "working"}>
            <FileText className="size-4" />
            {t("report.downloadForm")}
          </Button>
        </div>
      </div>
      {formState.kind === "note" ? (
        <p className="print-hide mt-3 text-sm text-muted-foreground">
          {formState.unplaced > 0
            ? t("report.formPartial", { count: formState.unplaced })
            : formState.export === "final"
              ? t("report.formFinal")
              : t("report.formReady")}
        </p>
      ) : null}
      {formState.kind === "failed" ? (
        <p role="alert" className="print-hide mt-3 text-sm text-destructive">
          {formState.message}
        </p>
      ) : null}

      {/* totals */}
      <section className="mt-8 rounded-xl border border-border bg-surface p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <p className="text-sm text-muted-foreground">{t("overview.totalSoFar")}</p>
          <p className="font-display text-3xl tabular-nums">
            {formatEur(detail.total_eur, formatLocale)}
          </p>
        </div>
        <Separator className="my-3" />
        <p className="text-sm text-muted-foreground">
          {itemisedWins
            ? t("report.itemisedWins", {
                allowance: formatEur(detail.pauschbetrag_eur, formatLocale),
              })
            : t("report.allowanceWins", {
                allowance: formatEur(detail.pauschbetrag_eur, formatLocale),
              })}
        </p>
      </section>

      {/* one block per expense: amount, form line, the calculation itself */}
      <div className="mt-6 space-y-4">
        {detail.expenses.map((expense) => (
          <section
            key={expense.category}
            className="print-plain rounded-xl border border-border bg-surface p-5"
          >
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <h2 className="text-base font-medium">
                <GermanTerm
                  original={
                    t.has(`categoriesOfficial.${expense.category}`)
                      ? t(`categoriesOfficial.${expense.category}`)
                      : ""
                  }
                >
                  {t.has(`categories.${expense.category}`)
                    ? t(`categories.${expense.category}`)
                    : expense.category}
                </GermanTerm>
              </h2>
              <p className="text-lg font-medium tabular-nums">
                {formatEur(expense.amount_eur, formatLocale)}
              </p>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{formLabel(expense, t)}</p>
            {expense.trace.length > 0 ? (
              <ul className="mt-3 space-y-1 border-l-2 border-border pl-3 text-sm text-muted-foreground">
                {expense.trace.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            ) : (
              <p className="mt-3 text-sm text-muted-foreground">{t("overview.sumOfReceipts")}</p>
            )}

            {expense.documents.length > 0 ? (
              <div className="mt-4">
                <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {t("report.evidence")}
                </h3>
                <ul className="mt-1.5 space-y-1 text-sm">
                  {expense.documents.map((document) => (
                    <li key={document}>{t("report.fromDocument", { document })}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            {/* The quotation is left in German and unabridged. It is the text of the
                law, and a translated or shortened one would be this product's wording
                presented as the Finanzamt's - which is the opposite of what a source
                beside a figure is for. The plain-language part is the formula above. */}
            {expense.citations.length > 0 ? (
              <div className="mt-4 space-y-3">
                <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {t("report.officialSource")}
                </h3>
                {expense.citations.map((citation) => (
                  <figure key={citation.rule_id} className="border-l-2 border-primary/50 pl-3">
                    <blockquote className="text-sm italic leading-relaxed" lang="de">
                      {citation.excerpt}
                    </blockquote>
                    <figcaption className="mt-1 text-xs text-muted-foreground">
                      {citation.reference} · {citation.title}
                    </figcaption>
                  </figure>
                ))}
              </div>
            ) : null}
          </section>
        ))}
      </div>

      {/* benefits belong to the Hauptvordruck and say so, never a row above */}
      {benefit != null ? (
        <section className="mt-6 rounded-xl border border-border bg-surface p-5">
          <h2 className="text-base font-medium">{t("report.benefitTitle")}</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            {t("report.benefitBody", { amount: formatEur(Number(benefit), formatLocale) })}
          </p>
        </section>
      ) : null}

      <Separator className="my-8" />
      <p className="text-xs text-muted-foreground">{t("report.disclaimer")}</p>

      {/* The report is where a wrong figure is noticed, so it is where the way back
          belongs. Printed pages do not carry it: the control is for the screen, and
          a sheet that invites the reader to click is a sheet that has lost its
          nerve. */}
      {!draft ? (
        <div className="print:hidden">
          <ReopenButton
            caseId={caseId}
            onReopened={() => void getCaseDetail(caseId).then(setDetail)}
          />
        </div>
      ) : null}
    </article>
  );
}
