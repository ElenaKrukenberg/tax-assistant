"use client";

import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type {
  ExpenseStatus,
  FindingSeverity,
  Provenance,
  TaxCaseStatus,
} from "@/features/cases/types";

const base = "rounded-md border px-2 py-0.5 text-xs font-medium";

export function CaseStatusBadge({ status }: { status: TaxCaseStatus }) {
  const t = useTranslations("cases");
  const tone: Record<TaxCaseStatus, string> = {
    gathering: "border-border-strong bg-muted text-muted-foreground",
    validating: "border-border-strong bg-surface-2 text-muted-foreground",
    needs_user_input: "border-warning/40 bg-warning/15 text-foreground",
    reviewing: "border-primary/30 bg-primary/10 text-primary",
    finalized: "border-success/40 bg-success/15 text-foreground",
  };

  return (
    <Badge variant="outline" className={cn(base, tone[status])}>
      {t(`status.${status}`)}
    </Badge>
  );
}

export function ExpenseStatusBadge({ status }: { status: ExpenseStatus }) {
  const t = useTranslations("cases");
  const tone: Record<ExpenseStatus, string> = {
    draft: "border-border-strong bg-muted text-muted-foreground",
    confirmed: "border-success/40 bg-success/15 text-foreground",
    flagged: "border-destructive/40 bg-destructive/10 text-destructive",
  };

  return (
    <Badge variant="outline" className={cn(base, tone[status])}>
      {t(`expenseStatus.${status}`)}
    </Badge>
  );
}

export function SeverityBadge({ severity }: { severity: FindingSeverity }) {
  const t = useTranslations("cases");
  const tone: Record<FindingSeverity, string> = {
    blocking: "border-destructive/40 bg-destructive/10 text-destructive",
    warning: "border-warning/40 bg-warning/15 text-foreground",
    suggestion: "border-border-strong bg-muted text-muted-foreground",
  };

  return (
    <Badge variant="outline" className={cn(base, "uppercase tracking-wide", tone[severity])}>
      {t(`severity.${severity}`)}
    </Badge>
  );
}

export function ProvenanceChip({ provenance }: { provenance: Provenance }) {
  const t = useTranslations("cases");
  return (
    <span className="inline-flex items-center rounded-md border border-border bg-surface-2 px-1.5 py-0.5 text-[11px] text-muted-foreground">
      {t(`provenance.${provenance}`)}
    </span>
  );
}
