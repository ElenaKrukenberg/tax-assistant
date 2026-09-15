"use client";

import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import {
  Calculator,
  ShieldCheck,
  ShieldAlert,
  ListChecks,
  HelpCircle,
  AlertTriangle,
  Info,
  CheckCircle2,
  Circle,
} from "lucide-react";

// Structured tool results rendered as cards (Day 5).
// Shapes mirror the backend domain models (domain/calculations.py etc.).

type CalculationData = {
  calculation_type: string;
  amount_eur: number;
  breakdown: string[];
  warnings?: string[];
};

type ValidationFinding = { rule_id: string; severity: string; message: string };
type ValidationData = { valid: boolean; findings: ValidationFinding[]; checked_rules: string[] };

type ChecklistItem = { document: string; required: boolean; note?: string };
type ChecklistData = {
  checklists: { category: string; items: ChecklistItem[]; general_note: string }[];
};

const EUR = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" });

export function ToolResultCard({ tool, data }: { tool: string; data: unknown }) {
  if (tool === "calculate_tax_amount") return <CalculationCard data={data as CalculationData} />;
  if (tool === "validate_tax_data") return <ValidationCard data={data as ValidationData} />;
  if (tool === "build_document_checklist") return <ChecklistCard data={data as ChecklistData} />;
  return null;
}

export function CalculationCard({ data }: { data: CalculationData }) {
  const t = useTranslations("cards");
  return (
    <section className="overflow-hidden rounded-2xl border border-border bg-surface shadow-elevated">
      <header className="flex items-center gap-2 border-b border-border bg-surface-2/50 px-4 py-2.5">
        <Calculator className="h-3.5 w-3.5 text-primary" />
        <span className="text-[11px] font-semibold uppercase tracking-wider text-primary">
          {t("calculation")}
        </span>
        <span className="text-[11px] text-muted-foreground">
          {t.has(`calcType.${data.calculation_type}`)
            ? t(`calcType.${data.calculation_type}`)
            : data.calculation_type}
        </span>
      </header>
      <div className="px-4 py-3">
        <div className="text-2xl font-semibold tracking-tight text-foreground">
          {EUR.format(data.amount_eur)}
        </div>
        <ul className="mt-2 space-y-1 text-[13px] leading-relaxed text-muted-foreground">
          {data.breakdown.map((b, i) => (
            <li key={i} className="flex gap-2">
              <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-border-strong" />
              {b}
            </li>
          ))}
        </ul>
        {data.warnings && data.warnings.length > 0 && (
          <ul className="mt-2 space-y-1 border-t border-border pt-2 text-xs text-warning">
            {data.warnings.map((w, i) => (
              <li key={i} className="flex gap-1.5">
                <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                {w}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

const SEVERITY_STYLE: Record<string, { icon: typeof Info; cls: string }> = {
  error: { icon: ShieldAlert, cls: "text-destructive" },
  warning: { icon: AlertTriangle, cls: "text-warning" },
  info: { icon: Info, cls: "text-muted-foreground" },
};

export function ValidationCard({ data }: { data: ValidationData }) {
  const t = useTranslations("cards");
  const Icon = data.valid ? ShieldCheck : ShieldAlert;
  return (
    <section className="overflow-hidden rounded-2xl border border-border bg-surface shadow-elevated">
      <header className="flex items-center gap-2 border-b border-border bg-surface-2/50 px-4 py-2.5">
        <Icon className={cn("h-3.5 w-3.5", data.valid ? "text-success" : "text-destructive")} />
        <span className="text-[11px] font-semibold uppercase tracking-wider text-primary">
          {t("validation")}
        </span>
        <span
          className={cn(
            "text-[11px] font-medium",
            data.valid ? "text-success" : "text-destructive",
          )}
        >
          {data.valid ? t("plausible") : t("issuesFound")}
        </span>
        <span className="ml-auto text-[11px] text-muted-foreground">
          {t("rulesChecked", { count: data.checked_rules.length })}
        </span>
      </header>
      <div className="px-4 py-3">
        {data.findings.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">{t("allPassed")}</p>
        ) : (
          <ul className="space-y-2">
            {data.findings.map((f, i) => {
              const s = SEVERITY_STYLE[f.severity] ?? SEVERITY_STYLE.info;
              return (
                <li key={i} className="flex gap-2 text-[13px] leading-relaxed">
                  <s.icon className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", s.cls)} />
                  <span>
                    <span
                      className={cn(
                        "mr-1.5 rounded bg-surface-2 px-1 py-0.5 font-mono text-[10px]",
                        s.cls,
                      )}
                    >
                      {f.rule_id}
                    </span>
                    {f.message}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}

export function ChecklistCard({ data }: { data: ChecklistData }) {
  const t = useTranslations("cards");
  return (
    <section className="overflow-hidden rounded-2xl border border-border bg-surface shadow-elevated">
      <header className="flex items-center gap-2 border-b border-border bg-surface-2/50 px-4 py-2.5">
        <ListChecks className="h-3.5 w-3.5 text-primary" />
        <span className="text-[11px] font-semibold uppercase tracking-wider text-primary">
          {t("checklist")}
        </span>
      </header>
      <div className="space-y-4 px-4 py-3">
        {data.checklists.map((c) => (
          <div key={c.category}>
            <div className="mb-1.5 text-[13px] font-semibold capitalize text-foreground">
              {c.category.replace(/_/g, " ")}
            </div>
            <ul className="space-y-1.5">
              {c.items.map((item, i) => (
                <li key={i} className="flex gap-2 text-[13px] leading-relaxed">
                  {item.required ? (
                    <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
                  ) : (
                    <Circle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground/50" />
                  )}
                  <span>
                    {item.document}
                    {!item.required && (
                      <span className="ml-1.5 text-[11px] text-muted-foreground">
                        {t("recommended")}
                      </span>
                    )}
                    {item.note && (
                      <span className="block text-xs text-muted-foreground">{item.note}</span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))}
        {data.checklists[0] && (
          <p className="border-t border-border pt-2 text-xs text-muted-foreground">
            {data.checklists[0].general_note}
          </p>
        )}
      </div>
    </section>
  );
}

export function ClarificationBanner() {
  const t = useTranslations("chat");
  return (
    <div className="flex items-center gap-2 rounded-xl border border-border bg-accent/60 px-4 py-2.5 text-[13px] text-foreground">
      <HelpCircle className="h-4 w-4 shrink-0 text-primary" />
      {t("clarification")}
    </div>
  );
}
