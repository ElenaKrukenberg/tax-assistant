"use client";

// The way back out of a finished return.
//
// Approving the report finalizes the case, and the tables enforce that: every later
// write is refused by a trigger. Until this button existed, a position declined by
// mistake was declined for good, and the API's own advice - "reopen it first" - named
// a door the product did not have. Reopening deletes the finished run and lifts the
// lock; the next advance rebuilds the interview from the tables, so nothing already
// answered is asked again.

import { useRouter } from "next/navigation";
import { RotateCcw } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { reopenCase } from "@/features/cases/api";

export function ReopenButton({
  caseId,
  onReopened,
}: {
  caseId: string;
  // The screens hold the case in their own state, so the one that knows how to
  // refresh does the refreshing; without it the page would keep showing a lock that
  // is no longer there.
  onReopened?: () => void;
}) {
  const t = useTranslations("cases");
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  return (
    <div className="mt-4">
      <p className="text-xs text-muted-foreground">{t("overview.reopenHint")}</p>
      <Button
        variant="outline"
        size="sm"
        className="mt-2"
        disabled={busy}
        onClick={() => {
          setBusy(true);
          setFailed(false);
          reopenCase(caseId)
            .then(() => {
              onReopened?.();
              router.refresh();
            })
            .catch(() => setFailed(true))
            .finally(() => setBusy(false));
        }}
      >
        <RotateCcw className="size-4" />
        {t("overview.reopen")}
      </Button>
      {failed ? (
        <p role="alert" className="mt-2 text-xs text-destructive">
          {t("overview.reopenFailed")}
        </p>
      ) : null}
    </div>
  );
}
