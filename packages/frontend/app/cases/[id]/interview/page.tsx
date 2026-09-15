"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { ArrowRight, CheckCircle2, ChevronLeft, HelpCircle, Pencil } from "lucide-react";
import { useState } from "react";

import { AgentWorking } from "@/components/cases/states";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { LiveInterview } from "@/components/cases/live-interview";
import { getTaxCase } from "@/features/cases/case-api.stub";
import { isLiveBackend } from "@/lib/supabase";
import { formatEur, messageKey } from "@/features/cases/format";
import { useLocale } from "@/i18n/locale-provider";

export default function InterviewPage() {
  const params0 = useParams<{ id: string }>();
  if (isLiveBackend) {
    return <LiveInterview caseId={params0.id} />;
  }
  return <FixtureInterviewPage />;
}

function FixtureInterviewPage() {
  const t = useTranslations("cases");
  const { locale } = useLocale();
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const taxCase = getTaxCase(params.id);
  const [days, setDays] = useState("96");
  const [finished, setFinished] = useState(false);

  return (
    <div className="mx-auto w-full max-w-2xl">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">{t("interview.progress")}</p>
        <Button variant="ghost" size="sm" onClick={() => setFinished((current) => !current)}>
          {finished ? t("interview.showQuestion") : t("interview.previewEnd")}
        </Button>
      </div>
      <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-muted">
        <div className="h-full w-2/3 rounded-full bg-primary" />
      </div>

      {finished ? (
        <section className="mt-10 rounded-xl border border-border bg-surface p-6">
          <CheckCircle2 className="size-6 text-success" aria-hidden="true" />
          <h1 className="mt-3 font-display text-3xl leading-tight">{t("interview.doneTitle")}</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {t("interview.doneBody", {
              questions: 7,
              documents: 2,
              categories: taxCase.expenses.length,
              total: formatEur(taxCase.expenseTotalEur, locale),
            })}
          </p>
          <Button asChild className="mt-6">
            <Link href={`/cases/${taxCase.id}/review`}>
              {t("interview.doneCta")}
              <ArrowRight className="size-4" />
            </Link>
          </Button>
        </section>
      ) : (
        <section className="mt-10">
          <p className="text-sm text-muted-foreground">{t("interview.why")}</p>
          <h1 className="mt-3 text-2xl font-medium leading-snug sm:text-3xl">
            {t("interview.question")}
          </h1>

          <div className="mt-8 space-y-4">
            <div className="space-y-2">
              <Label htmlFor="days">{t("interview.daysLabel")}</Label>
              <div className="flex items-center gap-2">
                <Input
                  id="days"
                  type="number"
                  inputMode="numeric"
                  min={0}
                  max={210}
                  value={days}
                  onChange={(event) => setDays(event.target.value)}
                  className="w-32 tabular-nums"
                />
                <span className="text-sm text-muted-foreground">{t("interview.daysUnit")}</span>
              </div>
            </div>
            <div className="space-y-2">
              <Label>{t("interview.quickPick")}</Label>
              <ToggleGroup
                type="single"
                value={days}
                onValueChange={(value) => value && setDays(value)}
                variant="outline"
                className="flex-wrap justify-start"
              >
                <ToggleGroupItem value="96">{t("interview.twoDays")}</ToggleGroupItem>
                <ToggleGroupItem value="144">{t("interview.threeDays")}</ToggleGroupItem>
              </ToggleGroup>
            </div>
          </div>

          <Collapsible className="mt-6">
            <CollapsibleTrigger className="inline-flex items-center gap-1.5 text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
              <HelpCircle className="size-4" aria-hidden="true" />
              {t("interview.disclosure")}
            </CollapsibleTrigger>
            <CollapsibleContent>
              <p className="mt-3 rounded-lg border border-border bg-surface-2 p-3 text-sm text-muted-foreground">
                {t("interview.disclosureBody")}
              </p>
            </CollapsibleContent>
          </Collapsible>

          <div className="mt-8 flex flex-wrap items-center gap-2">
            <Button onClick={() => setFinished(true)}>
              {t("common.continue")}
              <ArrowRight className="size-4" />
            </Button>
            <Button variant="outline" onClick={() => setFinished(true)}>
              {t("interview.skip")}
            </Button>
            <Button variant="ghost" onClick={() => router.back()}>
              <ChevronLeft className="size-4" />
              {t("common.back")}
            </Button>
          </div>

          <div className="mt-8">
            <AgentWorking
              title={t("interview.workingTitle")}
              steps={[
                t("interview.workingStep1"),
                t("interview.workingStep2"),
                t("interview.workingStep3"),
              ]}
              activeIndex={1}
            />
          </div>
        </section>
      )}

      <Separator className="my-10" />
      <section>
        <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
          {t("interview.answered")}
        </h2>
        <ul className="mt-3 divide-y divide-border overflow-hidden rounded-xl border border-border bg-surface">
          {taxCase.answeredQuestions.map((item) => (
            <li
              key={item.id}
              className="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="min-w-0">
                <p className="text-sm text-muted-foreground">
                  {t(`fixture.answers.${messageKey(item.id)}.question`)}
                </p>
                <p className="mt-0.5 text-sm font-medium">
                  {t(`fixture.answers.${messageKey(item.id)}.answer`)}
                </p>
              </div>
              <Button variant="ghost" size="sm" className="self-start">
                <Pencil className="size-3.5" />
                {t("common.edit")}
              </Button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
