"use client";

import Link from "next/link";
import { ArrowRight, Check, Lightbulb, Pencil, Quote, X } from "lucide-react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { ExpenseList } from "@/components/cases/expense-list";
import { LiveCaseOverview } from "@/components/cases/live-case-overview";
import { isLiveBackend } from "@/lib/supabase";
import { ProvenanceChip } from "@/components/cases/badges";
import { EmptyState } from "@/components/cases/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { getTaxCase } from "@/features/cases/case-api.stub";
import { formatEur, messageKey } from "@/features/cases/format";
import type { ProfileFieldDto } from "@/features/cases/types";
import { useLocale } from "@/i18n/locale-provider";

function ProfileRow({ field }: { field: ProfileFieldDto }) {
  const t = useTranslations("cases");
  const translatedValue = t.has(`fixture.profile.${messageKey(field.id)}.value`)
    ? t(`fixture.profile.${messageKey(field.id)}.value`)
    : field.value;
  const [editing, setEditing] = useState(false);
  const [editedValue, setEditedValue] = useState<string | null>(null);
  const value = editedValue ?? translatedValue;

  return (
    <div className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0 flex-1">
        <p className="text-xs text-muted-foreground">
          {t(`fixture.profile.${messageKey(field.id)}.label`)}
        </p>
        {editing ? (
          <Input
            className="mt-1 h-8"
            value={value}
            aria-label={t(`fixture.profile.${messageKey(field.id)}.label`)}
            onChange={(event) => setEditedValue(event.target.value)}
          />
        ) : (
          <p className="mt-0.5 flex flex-wrap items-center gap-2 text-sm text-foreground">
            {value}
            <ProvenanceChip provenance={field.provenance} />
          </p>
        )}
      </div>
      {editing ? (
        <div className="flex gap-1">
          <Button size="sm" onClick={() => setEditing(false)}>
            <Check className="size-3.5" />
            {t("common.saveDemo")}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setEditedValue(null);
              setEditing(false);
            }}
          >
            {t("common.cancel")}
          </Button>
        </div>
      ) : (
        <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>
          <Pencil className="size-3.5" />
          {t("common.edit")}
        </Button>
      )}
    </div>
  );
}

export default function CaseOverviewPage() {
  const paramsLive = useParams<{ id: string }>();
  if (isLiveBackend) {
    return <LiveCaseOverview caseId={paramsLive.id} />;
  }
  return <FixtureCaseOverview />;
}

function FixtureCaseOverview() {
  const t = useTranslations("cases");
  const { locale } = useLocale();
  const params = useParams<{ id: string }>();
  const taxCase = getTaxCase(params.id);
  const [dismissed, setDismissed] = useState<string[]>([]);
  const candidates = taxCase.gapCandidates.filter((item) => !dismissed.includes(item.id));
  const itemisedWins = taxCase.expenseTotalEur > taxCase.pauschbetragEur;

  return (
    <div className="space-y-10">
      <section className="rounded-xl border border-border bg-surface p-5">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">
              {t("overview.stage")}
            </p>
            <h1 className="mt-1 font-display text-3xl leading-none">{t("overview.stageValue")}</h1>
            <p className="mt-2 text-sm text-muted-foreground">{t("overview.remaining")}</p>
          </div>
          <Button asChild>
            <Link href={`/cases/${taxCase.id}/interview`}>
              {t("overview.nextAction")}
              <ArrowRight className="size-4" />
            </Link>
          </Button>
        </div>
        <Progress value={taxCase.progress} className="mt-5 h-1.5" />
      </section>

      <section>
        <h2 className="font-display text-2xl">{t("overview.profileTitle")}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{t("overview.profileSubtitle")}</p>
        <div className="mt-4 divide-y divide-border overflow-hidden rounded-xl border border-border bg-surface">
          {taxCase.profile.map((field) => (
            <ProfileRow key={field.id} field={field} />
          ))}
        </div>
      </section>

      <section>
        <h2 className="font-display text-2xl">{t("overview.expensesTitle")}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{t("overview.expensesSubtitle")}</p>
        <div className="mt-4">
          <ExpenseList expenses={taxCase.expenses} />
        </div>
      </section>

      <section className="rounded-xl border border-border-strong bg-surface p-5 shadow-elevated">
        <h2 className="font-display text-2xl">{t("overview.totalsTitle")}</h2>
        <dl className="mt-4 space-y-2 text-sm">
          <div className="flex items-baseline justify-between gap-4">
            <dt className="text-muted-foreground">{t("overview.sumLabel")}</dt>
            <dd className="font-medium tabular-nums">
              {formatEur(taxCase.expenseTotalEur, locale)}
            </dd>
          </div>
          <div className="flex items-baseline justify-between gap-4">
            <dt className="text-muted-foreground">{t("overview.pauschLabel")}</dt>
            <dd className="font-medium tabular-nums">
              {formatEur(taxCase.pauschbetragEur, locale)}
            </dd>
          </div>
        </dl>
        <Separator className="my-4" />
        <div className="flex items-end justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">
              {t("overview.applied")}
            </p>
            <p className="mt-1 text-sm text-muted-foreground">
              {itemisedWins ? t("overview.sumLabel") : t("overview.pauschLabel")}
            </p>
          </div>
          <p className="font-display text-4xl leading-none tabular-nums">
            {formatEur(itemisedWins ? taxCase.expenseTotalEur : taxCase.pauschbetragEur, locale)}
          </p>
        </div>
        <p className="mt-3 text-sm text-muted-foreground">{t("overview.winnerWhy")}</p>
      </section>

      <section>
        <h2 className="font-display text-2xl">{t("overview.gapsTitle")}</h2>
        <div className="mt-4 space-y-3">
          {candidates.length === 0 ? (
            <EmptyState
              title={t("overview.emptyGapTitle")}
              description={t("overview.emptyGapBody")}
            />
          ) : (
            candidates.map((candidate) => (
              <div key={candidate.id} className="rounded-xl border border-border bg-surface p-4">
                <div className="flex items-start justify-between gap-3">
                  <p className="flex items-center gap-2 text-sm font-medium">
                    <Lightbulb className="size-4 text-primary" aria-hidden="true" />
                    {candidate.categoryLabel}
                  </p>
                  <Button
                    size="icon"
                    variant="ghost"
                    aria-label={t("common.dismiss")}
                    className="size-8"
                    onClick={() => setDismissed((previous) => [...previous, candidate.id])}
                  >
                    <X className="size-4" />
                  </Button>
                </div>
                <p className="mt-2 text-sm text-muted-foreground">
                  {t(`fixture.gaps.${candidate.id}.rationale`)}
                </p>
                <blockquote className="mt-3 border-l-2 border-primary/50 pl-3 text-sm italic">
                  {candidate.officialSource.excerpt}
                </blockquote>
                <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Quote className="size-3.5" aria-hidden="true" />
                  {candidate.officialSource.title} · {candidate.officialSource.reference}
                </p>
                <div className="mt-4 flex gap-2">
                  <Button
                    size="sm"
                    onClick={() => setDismissed((previous) => [...previous, candidate.id])}
                  >
                    {t("overview.confirmGap")}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setDismissed((previous) => [...previous, candidate.id])}
                  >
                    {t("overview.notApplicable")}
                  </Button>
                </div>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
