"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { ArrowRight, CheckCircle2, ShieldCheck, ThumbsDown, Wrench } from "lucide-react";
import { useState } from "react";

import { SeverityBadge } from "@/components/cases/badges";
import { LiveReview } from "@/components/cases/live-review";
import { AgentWorking, EmptyState } from "@/components/cases/states";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { getTaxCase } from "@/features/cases/case-api.stub";
import { formatEur } from "@/features/cases/format";
import { useLocale } from "@/i18n/locale-provider";
import { isLiveBackend } from "@/lib/supabase";

export default function ReviewPage() {
  const params = useParams<{ id: string }>();
  if (isLiveBackend) {
    return <LiveReview caseId={params.id} />;
  }
  return <FixtureReviewPage />;
}

function FixtureReviewPage() {
  const t = useTranslations("cases");
  const { locale } = useLocale();
  const params = useParams<{ id: string }>();
  const taxCase = getTaxCase(params.id);
  const [resolved, setResolved] = useState<string[]>([]);
  const [noteOpen, setNoteOpen] = useState<string | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const findings = taxCase.findings.filter((finding) => !resolved.includes(finding.id));
  const blocking = findings.some((finding) => finding.severity === "blocking");
  const canApprove = !blocking && acknowledged;

  return (
    <div className="space-y-8">
      <div>
        <p className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
          <ShieldCheck className="size-4" aria-hidden="true" />
          {t("review.eyebrow")}
        </p>
        <h1 className="mt-2 font-display text-4xl leading-tight">{t("review.title")}</h1>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">{t("review.subtitle")}</p>
      </div>

      <AgentWorking
        title={t("review.workingTitle")}
        steps={[t("review.workingStep1"), t("review.workingStep2"), t("review.workingStep3")]}
        activeIndex={2}
      />

      <div className="space-y-3">
        {findings.length === 0 ? (
          <EmptyState title={t("review.cleanTitle")} description={t("review.cleanBody")} />
        ) : (
          findings.map((finding) => {
            const expense = taxCase.expenses.find((item) => item.id === finding.affectedExpenseId);
            return (
              <div key={finding.id} className="rounded-xl border border-border bg-surface p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <SeverityBadge severity={finding.severity} />
                  <p className="text-sm font-medium">{t(`fixture.findings.${finding.id}.title`)}</p>
                </div>
                <p className="mt-2 text-sm text-muted-foreground">
                  {t(`fixture.findings.${finding.id}.reasoning`)}
                </p>
                {expense ? (
                  <p className="mt-3 text-xs text-muted-foreground">
                    {t("review.affected")}:{" "}
                    <span className="text-foreground tabular-nums">
                      {expense.categoryLabel} — {formatEur(expense.amountEur, locale)}
                    </span>
                  </p>
                ) : null}
                <div className="mt-4 flex flex-wrap gap-2">
                  <Button size="sm" asChild>
                    <Link href={`/cases/${taxCase.id}/interview`}>
                      <Wrench className="size-3.5" />
                      {t("review.fix")}
                    </Link>
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setNoteOpen(noteOpen === finding.id ? null : finding.id)}
                  >
                    <ThumbsDown className="size-3.5" />
                    {t("review.disagree")}
                  </Button>
                </div>
                {noteOpen === finding.id ? (
                  <div className="mt-3 space-y-2">
                    <Textarea placeholder={t("review.notePlaceholder")} rows={3} />
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => {
                        setResolved((previous) => [...previous, finding.id]);
                        setNoteOpen(null);
                      }}
                    >
                      {t("review.saveResolution")}
                    </Button>
                  </div>
                ) : null}
              </div>
            );
          })
        )}
      </div>

      <Separator />
      <section className="rounded-xl border border-border-strong bg-surface p-5">
        <h2 className="font-display text-2xl">{t("review.gateTitle")}</h2>
        <div className="mt-4 flex items-start gap-3">
          <Checkbox
            id="ack"
            checked={acknowledged}
            onCheckedChange={(value) => setAcknowledged(value === true)}
          />
          <Label
            htmlFor="ack"
            className="text-sm font-normal leading-relaxed text-muted-foreground"
          >
            {t("review.gateAck")}
          </Label>
        </div>
        <div className="mt-5 flex flex-wrap items-center gap-3">
          {canApprove ? (
            <Button asChild>
              <Link href={`/cases/${taxCase.id}/report`}>
                <CheckCircle2 className="size-4" />
                {t("review.approve")}
                <ArrowRight className="size-4" />
              </Link>
            </Button>
          ) : (
            <Button disabled>
              <CheckCircle2 className="size-4" />
              {t("review.approve")}
              <ArrowRight className="size-4" />
            </Button>
          )}
          {blocking ? <p className="text-xs text-destructive">{t("review.blocked")}</p> : null}
        </div>
      </section>
    </div>
  );
}
