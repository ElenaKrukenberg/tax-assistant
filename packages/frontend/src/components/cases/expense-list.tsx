"use client";

import { ChevronDown, FileWarning, MessageSquareText, Paperclip, Quote } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { ExpenseStatusBadge } from "@/components/cases/badges";
import { Separator } from "@/components/ui/separator";
import { useLocale } from "@/i18n/locale-provider";
import { formatEur } from "@/features/cases/format";
import type { EvidenceDto, ExpenseDto } from "@/features/cases/types";
import { cn } from "@/lib/utils";

function Evidence({ evidence }: { evidence: EvidenceDto[] }) {
  const t = useTranslations("cases");
  if (evidence.length === 0) {
    return (
      <span className="inline-flex items-center gap-1.5 text-sm text-destructive">
        <FileWarning className="h-4 w-4 shrink-0" aria-hidden="true" />
        {t("expenses.noEvidence")}
      </span>
    );
  }

  const Icon = evidence.some((item) => item.provenance === "document")
    ? Paperclip
    : MessageSquareText;
  return (
    <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
      <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
      {evidence.length === 1
        ? evidence[0]?.label
        : t("expenses.evidenceCount", { count: evidence.length })}
    </span>
  );
}

function Trace({ expense }: { expense: ExpenseDto }) {
  const t = useTranslations("cases");
  const { locale } = useLocale();
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-surface-2 p-4">
      <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {t("expenses.trace")}
      </p>
      <div className="mt-3 grid gap-5 md:grid-cols-2">
        <div className="space-y-4">
          <div>
            <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {t("expenses.formula")}
            </h4>
            <p className="mt-1.5 font-mono text-sm">{expense.formula}</p>
          </div>

          <div>
            <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {t("expenses.values")}
            </h4>
            <p className="mt-1.5 whitespace-pre-wrap font-mono text-sm">
              {expense.substitutedValues}
            </p>
          </div>

          <div>
            <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {t("expenses.result")}
            </h4>
            <p className="mt-1.5 font-display text-2xl tabular-nums">
              {formatEur(expense.amountEur, locale)}
            </p>
          </div>

          <div>
            <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {t("expenses.evidence")}
            </h4>
            <ul className="mt-1.5 space-y-1">
              {expense.evidence.map((item) => (
                <li key={item.label} className="text-sm">
                  {item.label}
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="space-y-3">
          <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {t("expenses.officialSource")}
          </h4>
          <blockquote className="relative border-l-2 border-primary/50 pl-4">
            <Quote
              className="absolute -left-2 -top-1 h-4 w-4 text-muted-foreground/50"
              aria-hidden="true"
            />
            <p className="text-sm italic leading-relaxed">{expense.officialSource.excerpt}</p>
          </blockquote>
          <p className="text-xs text-muted-foreground">
            {expense.officialSource.title} · {expense.officialSource.reference}
          </p>
        </div>
      </div>
    </div>
  );
}

export function ExpenseList({ expenses }: { expenses: ExpenseDto[] }) {
  const t = useTranslations("cases");
  const { locale } = useLocale();
  const [open, setOpen] = useState<string | null>(expenses[0]?.id ?? null);

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface">
      <div className="hidden grid-cols-[1.4fr_0.8fr_1.4fr_1fr_0.8fr_2rem] gap-3 border-b border-border bg-surface-2 px-4 py-2.5 text-xs font-medium uppercase tracking-wide text-muted-foreground md:grid md:items-center">
        <span>{t("expenses.category")}</span>
        <span className="text-right">{t("expenses.amount")}</span>
        <span>{t("expenses.evidence")}</span>
        <span>{t("expenses.formLine")}</span>
        <span>{t("expenses.status")}</span>
        <span className="sr-only">{t("expenses.showTrace")}</span>
      </div>
      <ul>
        {expenses.map((expense) => {
          const expanded = open === expense.id;
          return (
            <li key={expense.id} className="group border-b border-border last:border-b-0">
              <button
                type="button"
                aria-expanded={expanded}
                onClick={() => setOpen(expanded ? null : expense.id)}
                className={cn(
                  "grid w-full grid-cols-1 gap-2 px-4 py-3 text-left transition-colors duration-200 ease-out hover:bg-accent/60 md:grid-cols-[1.4fr_0.8fr_1.4fr_1fr_0.8fr_2rem] md:items-center md:gap-3",
                  expanded && "bg-accent/40",
                )}
              >
                <span className="text-sm font-medium text-foreground">{expense.categoryLabel}</span>
                <span className="text-sm font-medium text-foreground tabular-nums md:text-right">
                  {formatEur(expense.amountEur, locale)}
                </span>
                <Evidence evidence={expense.evidence} />
                <span className="text-sm text-muted-foreground">{expense.formLine}</span>
                <span>
                  <ExpenseStatusBadge status={expense.status} />
                </span>
                <ChevronDown
                  className={cn(
                    "hidden size-4 justify-self-end text-muted-foreground transition-transform duration-200 ease-out group-hover:text-foreground md:block",
                    expanded && "rotate-180",
                  )}
                  aria-hidden="true"
                />
                <span className="text-xs text-muted-foreground md:hidden">
                  {expanded ? t("expenses.hideTrace") : t("expenses.showTrace")}
                </span>
              </button>
              {expanded ? (
                <div className="px-4 pb-4">
                  <Trace expense={expense} />
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
