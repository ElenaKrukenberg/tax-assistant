"use client";

import { AlertCircle, Check, FlaskConical, Loader2, RefreshCw, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

export function DemoModeBanner() {
  const t = useTranslations("cases");
  return (
    <div
      role="status"
      className="print-hide flex items-start gap-2 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2 text-sm text-muted-foreground"
    >
      <FlaskConical className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden="true" />
      <span>{t("common.demoMode")}</span>
    </div>
  );
}

export function InlineError({
  title,
  description,
  onRetry,
}: {
  title: string;
  description: string;
  onRetry?: () => void;
}) {
  const t = useTranslations("cases");
  return (
    <Alert variant="destructive" className="border-destructive/40 bg-destructive/5">
      <AlertCircle className="size-4" />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription className="flex flex-col items-start gap-2">
        <span>{description}</span>
        {onRetry ? (
          <Button size="sm" variant="outline" onClick={onRetry}>
            <RefreshCw className="size-3.5" />
            {t("common.retry")}
          </Button>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}

export function AgentWorking({
  title,
  steps,
  activeIndex,
}: {
  title: string;
  steps: string[];
  activeIndex: number;
}) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="flex items-center gap-2 text-sm font-medium text-foreground">
        <Sparkles className="size-4 text-primary" aria-hidden="true" />
        {title}
      </div>
      <ol className="mt-3 space-y-2" aria-live="polite">
        {steps.map((step, index) => {
          const state = index < activeIndex ? "done" : index === activeIndex ? "active" : "todo";
          return (
            <li key={step} className="flex items-center gap-2 text-sm">
              {state === "done" ? (
                <Check className="size-4 text-success" aria-hidden="true" />
              ) : state === "active" ? (
                <Loader2 className="size-4 animate-spin text-primary" aria-hidden="true" />
              ) : (
                <span
                  className="size-4 rounded-full border border-border-strong"
                  aria-hidden="true"
                />
              )}
              <span className={state === "todo" ? "text-muted-foreground" : "text-foreground"}>
                {step}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export function RowsSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={index}
          className="flex items-center justify-between rounded-lg border border-border bg-surface px-4 py-3"
        >
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-4 w-20" />
        </div>
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-dashed border-border-strong bg-surface-2 px-6 py-10 text-center">
      <p className="text-sm font-medium text-foreground">{title}</p>
      <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">{description}</p>
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  );
}
