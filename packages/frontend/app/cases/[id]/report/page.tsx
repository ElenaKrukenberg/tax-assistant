"use client";

import { Download, FileWarning, Paperclip, Printer, Quote } from "lucide-react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { LiveReport } from "@/components/cases/live-report";
import { getTaxCase } from "@/features/cases/case-api.stub";
import { isLiveBackend } from "@/lib/supabase";
import { formatCaseDate, formatEur } from "@/features/cases/format";
import { useLocale } from "@/i18n/locale-provider";

function downloadMarkdown(filename: string, content: string) {
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function ReportPage() {
  const paramsLive = useParams<{ id: string }>();
  if (isLiveBackend) {
    return <LiveReport caseId={paramsLive.id} />;
  }
  return <FixtureReportPage />;
}

function FixtureReportPage() {
  const t = useTranslations("cases");
  const { locale } = useLocale();
  const params = useParams<{ id: string }>();
  const taxCase = getTaxCase(params.id);
  const itemisedWins = taxCase.expenseTotalEur > taxCase.pauschbetragEur;
  const applied = itemisedWins ? taxCase.expenseTotalEur : taxCase.pauschbetragEur;

  function markdown() {
    const rows = taxCase.expenses
      .map(
        (expense) =>
          `## ${expense.categoryLabel}\n\n- ${t("report.amount")}: ${formatEur(expense.amountEur, locale)}\n- ${t("report.formLine")}: ${expense.formLine}\n- ${t("report.formula")}: ${expense.formula}\n- ${t("report.values")}: ${expense.substitutedValues}\n- ${t("report.source")}: ${expense.officialSource.title}, ${expense.officialSource.reference}`,
      )
      .join("\n\n");
    return `# ${t("report.title")}\n\n${t("common.taxYear")}: ${taxCase.taxYear}\n\n${rows}\n\n---\n\n${t("report.disclaimer")}\n`;
  }

  return (
    <article className="print-plain mx-auto w-full max-w-3xl">
      <div className="print-hide mb-6 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-sm text-foreground">
        {t("report.previewNotice")}
      </div>
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl leading-tight">{t("report.title")}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("common.taxYear")} {taxCase.taxYear}, Anlage N
          </p>
          <p className="text-sm text-muted-foreground">
            {t("report.generated", { date: formatCaseDate(taxCase.lastTouchedIso, locale) })}
          </p>
        </div>
        <div className="flex gap-2 print-hide">
          <Button variant="outline" onClick={() => window.print()}>
            <Printer className="size-4" />
            {t("report.print")}
          </Button>
          <Button
            variant="outline"
            onClick={() => downloadMarkdown(`anlage-n-${taxCase.taxYear}-demo.md`, markdown())}
          >
            <Download className="size-4" />
            {t("report.markdown")}
          </Button>
        </div>
      </header>

      <Separator className="my-8" />
      <section>
        <h2 className="font-display text-2xl">{t("report.summary")}</h2>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[560px] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                <th className="py-2 font-medium">{t("expenses.category")}</th>
                <th className="py-2 text-right font-medium">{t("report.amount")}</th>
                <th className="py-2 text-right font-medium">{t("report.formLine")}</th>
              </tr>
            </thead>
            <tbody>
              {taxCase.expenses.map((expense) => (
                <tr key={expense.id} className="border-b border-border">
                  <td className="py-2">{expense.categoryLabel}</td>
                  <td className="py-2 text-right tabular-nums">
                    {formatEur(expense.amountEur, locale)}
                  </td>
                  <td className="py-2 text-right text-muted-foreground">{expense.formLine}</td>
                </tr>
              ))}
              <tr className="border-b border-border">
                <td className="py-2 font-medium">{t("report.itemisedTotal")}</td>
                <td className="py-2 text-right font-medium tabular-nums">
                  {formatEur(taxCase.expenseTotalEur, locale)}
                </td>
                <td />
              </tr>
              <tr className="border-b border-border">
                <td className="py-2 text-muted-foreground">{t("overview.pauschLabel")}</td>
                <td className="py-2 text-right text-muted-foreground tabular-nums">
                  {formatEur(taxCase.pauschbetragEur, locale)}
                </td>
                <td />
              </tr>
              <tr>
                <td className="py-3 font-medium">{t("overview.applied")}</td>
                <td className="py-3 text-right font-display text-2xl tabular-nums">
                  {formatEur(applied, locale)}
                </td>
                <td />
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <Separator className="my-8" />
      <section>
        <h2 className="font-display text-2xl">{t("report.detail")}</h2>
        <div className="mt-4 space-y-6">
          {taxCase.expenses.map((expense) => (
            <div
              key={expense.id}
              className="print-plain rounded-xl border border-border bg-surface p-5"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-base font-medium">{expense.categoryLabel}</h3>
                <p className="font-display text-2xl tabular-nums">
                  {formatEur(expense.amountEur, locale)}
                </p>
              </div>
              <dl className="mt-4 space-y-2 text-sm">
                <div>
                  <dt className="text-xs text-muted-foreground">{t("report.formula")}</dt>
                  <dd className="font-mono text-[13px]">{expense.formula}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">{t("report.values")}</dt>
                  <dd className="font-mono text-[13px]">{expense.substitutedValues}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">{t("report.evidence")}</dt>
                  <dd className="space-y-1">
                    {expense.evidence.length > 0 ? (
                      expense.evidence.map((evidence) => (
                        <span key={evidence.label} className="flex items-center gap-1.5">
                          <Paperclip
                            className="size-3.5 text-muted-foreground"
                            aria-hidden="true"
                          />
                          {evidence.label}
                        </span>
                      ))
                    ) : (
                      <span className="flex items-center gap-1.5 text-destructive">
                        <FileWarning className="size-3.5" aria-hidden="true" />
                        {t("expenses.noEvidence")}
                      </span>
                    )}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">{t("report.formLine")}</dt>
                  <dd>{expense.formLine}</dd>
                </div>
              </dl>
              <p className="mt-4 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                {t("report.source")}
              </p>
              <blockquote className="mt-2 border-l-2 border-primary/50 pl-3 text-sm italic">
                {expense.officialSource.excerpt}
              </blockquote>
              <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
                <Quote className="size-3.5" aria-hidden="true" />
                {expense.officialSource.title} · {expense.officialSource.reference}
              </p>
            </div>
          ))}
        </div>
      </section>

      <Separator className="my-8" />
      <footer className="pb-6 text-xs leading-relaxed text-muted-foreground">
        {t("report.disclaimer")}
      </footer>
    </article>
  );
}
