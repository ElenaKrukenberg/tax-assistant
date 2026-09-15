"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, BrainCircuit, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { AuthErrorNotice } from "@/components/cases/auth-error-notice";
import { CaseStatusBadge } from "@/components/cases/badges";
import type { TaxCaseStatus } from "@/features/cases/types";
import { DemoModeBanner, EmptyState } from "@/components/cases/states";
import { AppNav } from "@/components/gta/app-nav";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ApiError,
  createCase,
  deleteAllCases,
  deleteCase,
  forgetProfileMemory,
  listCases,
} from "@/features/cases/api";
import { listTaxCases } from "@/features/cases/case-api.stub";
import { formatCaseDate, formatEur } from "@/features/cases/format";
import { useSession } from "@/hooks/use-session";
import { useLocale } from "@/i18n/locale-provider";
import { isLiveBackend } from "@/lib/supabase";

// One row shape for both worlds: the fixture carries progress and totals the API
// does not have yet, so those render only when present.
type Row = {
  id: string;
  taxYear: number;
  status: string;
  progress?: number;
  expenseTotalEur?: number;
  lastTouchedIso?: string;
};

const CURRENT_TAX_YEAR = 2025;

export default function CasesPage() {
  const t = useTranslations("cases");
  const { locale } = useLocale();
  const router = useRouter();
  const session = useSession();

  const [rows, setRows] = useState<Row[] | null>(isLiveBackend ? null : fixtureRows());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      const cases = await listCases();
      setRows(cases.map((c) => ({ id: c.id, taxYear: c.tax_year, status: c.status })));
      setError(null);
    } catch (exc) {
      if (exc instanceof ApiError && exc.status === 401) {
        router.replace("/login");
        return;
      }
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  }, [router]);

  useEffect(() => {
    if (!isLiveBackend) return;
    if (session.status === "signed_out") {
      router.replace("/login");
      return;
    }
    if (session.status === "signed_in") void reload();
  }, [session.status, reload, router]);

  async function start() {
    if (!isLiveBackend) {
      router.push("/cases/2025");
      return;
    }
    setBusy(true);
    try {
      const created = await createCase(CURRENT_TAX_YEAR);
      router.push(`/cases/${created.id}`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
      setBusy(false);
    }
  }

  async function remove(id: string) {
    // The product's promise: a case and everything in it, gone (Q11). "Everything in
    // it" is now true of both stores that hold the answers - the tables and the paused
    // graph run - which is what the confirmation text is careful to scope. The confirm
    // is the browser's; a custom dialog can come with the polish pass.
    if (!window.confirm(t("list.deleteConfirm"))) return;
    try {
      await deleteCase(id);
      await reload();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  }

  async function removeAll() {
    if (!window.confirm(t("list.deleteAllConfirm"))) return;
    setBusy(true);
    try {
      await deleteAllCases();
      await reload();
    } catch (exc) {
      // The backend answers 204 only when every case is gone; a partial failure is a
      // 500 naming how many are left, and repeating the action finishes them. So the
      // list is reloaded either way - what survived has to stay visible.
      setError(exc instanceof Error ? exc.message : String(exc));
      await reload();
    } finally {
      setBusy(false);
    }
  }

  async function forgetMe() {
    if (!window.confirm(t("list.forgetConfirm"))) return;
    setBusy(true);
    try {
      await forgetProfileMemory();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  const loading = isLiveBackend && rows === null && error === null;

  return (
    <div className="min-h-dvh bg-background">
      <AppNav />
      <main className="mx-auto w-full max-w-3xl px-4 py-12 sm:px-6">
        <AuthErrorNotice />
        {!isLiveBackend ? <DemoModeBanner /> : null}
        <div className="mt-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="font-display text-4xl leading-tight">{t("list.title")}</h1>
            <p className="mt-1 text-sm text-muted-foreground">{t("list.subtitle")}</p>
          </div>
          <Button onClick={start} disabled={busy}>
            <Plus className="size-4" />
            {t("list.start")}
          </Button>
        </div>

        {error ? (
          <p
            role="alert"
            className="mt-6 rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm"
          >
            {error}
          </p>
        ) : null}

        <div className="mt-8 space-y-3">
          {loading ? (
            <>
              <Skeleton className="h-32 w-full rounded-xl" />
              <Skeleton className="h-32 w-full rounded-xl" />
            </>
          ) : rows === null || rows.length === 0 ? (
            <EmptyState
              title={t("list.emptyTitle")}
              description={t("list.emptyBody")}
              action={
                <Button onClick={start} disabled={busy}>
                  <Plus className="size-4" />
                  {t("list.start")}
                </Button>
              }
            />
          ) : (
            rows.map((taxCase) => (
              <div
                key={taxCase.id}
                className="rounded-xl border border-border bg-surface transition-colors hover:border-border-strong hover:bg-accent/40"
              >
                <Link href={`/cases/${taxCase.id}`} className="block p-5">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex items-baseline gap-3">
                      <span className="font-display text-4xl leading-none">{taxCase.taxYear}</span>
                      <CaseStatusBadge status={taxCase.status as TaxCaseStatus} />
                    </div>
                    <ArrowRight className="size-4 text-muted-foreground" aria-hidden="true" />
                  </div>
                  {taxCase.progress !== undefined ? (
                    <Progress value={taxCase.progress} className="mt-4 h-1.5" />
                  ) : null}
                  {taxCase.expenseTotalEur !== undefined || taxCase.lastTouchedIso ? (
                    <div className="mt-4 flex flex-wrap items-end justify-between gap-3">
                      {taxCase.expenseTotalEur !== undefined ? (
                        <div>
                          <p className="text-xs text-muted-foreground">{t("list.expensesFound")}</p>
                          <p className="mt-0.5 text-lg font-medium tabular-nums">
                            {formatEur(taxCase.expenseTotalEur, locale)}
                          </p>
                        </div>
                      ) : null}
                      {taxCase.lastTouchedIso ? (
                        <p className="text-xs text-muted-foreground">
                          {t("list.lastUpdated", {
                            date: formatCaseDate(taxCase.lastTouchedIso, locale),
                          })}
                        </p>
                      ) : null}
                    </div>
                  ) : null}
                </Link>
                {isLiveBackend ? (
                  <div className="border-t border-border px-5 py-2 text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-muted-foreground hover:text-destructive"
                      onClick={() => void remove(taxCase.id)}
                    >
                      <Trash2 className="size-4" />
                      {t("list.delete")}
                    </Button>
                  </div>
                ) : null}
              </div>
            ))
          )}
        </div>

        {/* The two erasures sit together so the difference between them is visible.
            Deleting every case leaves the profile memory standing, and forgetting the
            person leaves the cases standing - separate choices by design (ADR 0011),
            which is only true for the user if the screen says so. */}
        {isLiveBackend ? (
          <div className="mt-8 space-y-3 border-t border-border pt-4">
            {rows !== null && rows.length > 0 ? (
              <div className="text-right">
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-muted-foreground hover:text-destructive"
                  onClick={() => void removeAll()}
                  disabled={busy}
                >
                  <Trash2 className="size-4" />
                  {t("list.deleteAll")}
                </Button>
              </div>
            ) : null}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="max-w-md text-xs text-muted-foreground">{t("list.forgetHint")}</p>
              <Button
                variant="ghost"
                size="sm"
                className="text-muted-foreground hover:text-destructive"
                onClick={() => void forgetMe()}
                disabled={busy}
              >
                <BrainCircuit className="size-4" />
                {t("list.forget")}
              </Button>
            </div>
          </div>
        ) : null}
      </main>
    </div>
  );
}

function fixtureRows(): Row[] {
  return listTaxCases().map((c) => ({
    id: c.id,
    taxYear: c.taxYear,
    status: c.status,
    progress: c.progress,
    expenseTotalEur: c.expenseTotalEur,
    lastTouchedIso: c.lastTouchedIso,
  }));
}
