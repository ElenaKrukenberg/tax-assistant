"use client";

// What the Reviewer actually said about this case, read from the tables.
//
// Read-only on purpose. A finding is answered inside the interview, where the graph
// pauses on it and the answer ("revise" or "dismiss") is what routes the run — a
// second place to answer the same finding would be a second source of truth about a
// paused run, and the two would disagree the first time somebody used both.
//
// Empty means two different things and the screen has to say which: the review has
// not run yet (the interview is unfinished), or it ran and raised nothing. The case
// status is what tells them apart, not the length of the list.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, FileText, MessagesSquare, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { SeverityBadge } from "@/components/cases/badges";
import { EmptyState } from "@/components/cases/states";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, type LiveCaseDetail, getCaseDetail } from "@/features/cases/api";

export function LiveReview({ caseId }: { caseId: string }) {
  const t = useTranslations("cases");
  const router = useRouter();
  const [detail, setDetail] = useState<LiveCaseDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  const header = (
    <div>
      <p className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
        <ShieldCheck className="size-4" aria-hidden="true" />
        {t("review.eyebrow")}
      </p>
      <h1 className="mt-2 font-display text-4xl leading-tight">{t("review.title")}</h1>
      <p className="mt-2 max-w-2xl text-sm text-muted-foreground">{t("review.subtitle")}</p>
    </div>
  );

  if (error) {
    return (
      <div className="space-y-8">
        {header}
        <p
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm"
        >
          {error}
        </p>
      </div>
    );
  }
  if (!detail) {
    return (
      <div className="space-y-8">
        {header}
        <Skeleton className="h-48 w-full rounded-xl" />
      </div>
    );
  }

  // The Reviewer runs at the end of the interview, so before then there is nothing
  // to show and saying "no findings" would be a claim nobody has made yet.
  const reviewed = detail.status === "finalized" || detail.findings.length > 0;

  return (
    <div className="space-y-8">
      {header}

      {/* A rules-only pass is not a second opinion, and it must not look like one.
          Shown above the findings, and above "the Reviewer raised nothing" too -
          that is the case where a degraded review is least visible (#29). */}
      {reviewed && detail.review_from_model === false ? (
        <p
          role="status"
          className="rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-sm"
        >
          {t("review.degraded")}
          {detail.review_note ? ` ${detail.review_note}` : ""}
        </p>
      ) : null}

      {!reviewed ? (
        <EmptyState
          title={t("review.notYetTitle")}
          description={t("review.notYetBody")}
          action={
            <Button asChild>
              <Link href={`/cases/${caseId}/interview`}>
                <MessagesSquare className="size-4" />
                {t("review.openInterview")}
              </Link>
            </Button>
          }
        />
      ) : detail.findings.length === 0 ? (
        <EmptyState title={t("review.liveCleanTitle")} description={t("review.liveCleanBody")} />
      ) : (
        <>
          <p className="text-sm text-muted-foreground">{t("review.answeredInInterview")}</p>
          <div className="space-y-3">
            {detail.findings.map((finding, index) => (
              <div
                key={`${finding.severity}-${finding.title}-${index}`}
                className="rounded-xl border border-border bg-surface p-4"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <SeverityBadge severity={finding.severity} />
                  <p className="text-sm font-medium">{finding.title}</p>
                </div>
                <p className="mt-2 text-sm text-muted-foreground">{finding.reasoning}</p>
                {finding.category ? (
                  <p className="mt-3 text-xs text-muted-foreground">
                    {t("review.affected")}:{" "}
                    <span className="text-foreground">
                      {t.has(`categories.${finding.category}`)
                        ? t(`categories.${finding.category}`)
                        : finding.category}
                    </span>
                  </p>
                ) : null}
              </div>
            ))}
          </div>
        </>
      )}

      {detail.status === "finalized" ? (
        <Button asChild>
          <Link href={`/cases/${caseId}/report`}>
            <FileText className="size-4" />
            {t("review.openReport")}
            <ArrowRight className="size-4" />
          </Link>
        </Button>
      ) : null}
    </div>
  );
}
