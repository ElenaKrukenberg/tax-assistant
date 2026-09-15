"use client";

// The case dashboard on live data: what the tables know right now, computed by
// the same code the review audits (the backend's expense_rows), never by the UI.
//
// A fresh case is empty on purpose. The system's defaults exist only as marked
// assumptions with a reason, confirmed by the user before any report (ADR 0010) —
// values like the yearly working days are deliberately not guessed at all, because
// they vary with the employment period and the Reviewer's contradiction check
// hinges on them. An empty dashboard therefore points at the interview instead of
// pretending to know.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, ChevronDown, MessagesSquare } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { ProvenanceChip } from "@/components/cases/badges";
import { GermanTerm } from "@/components/cases/german-term";
import { ReopenButton } from "@/components/cases/reopen-button";
import { EmptyState } from "@/components/cases/states";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Separator } from "@/components/ui/separator";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ApiError,
  type LiveCaseDetail,
  type LiveFieldValue,
  correctField,
  getCaseDetail,
  removeItem,
} from "@/features/cases/api";
import { formLabel, formatEur, messageKey } from "@/features/cases/format";
import { useLocale } from "@/i18n/locale-provider";

/**
 * One known fact, and the way to correct it without walking back through the interview.
 *
 * The editable thing is the fact, never the total it feeds (#12, #28). A figure is a
 * read over the facts, so an edit to the rendered number would leave the trace saying a
 * formula produced something it did not - and the promise the whole product rests on is
 * that any figure can show where it came from.
 *
 * A correction is not free and the row says so before it is made: positions the user
 * already approved that depended on this value go back to them, and the Reviewer's
 * findings are dropped because every one of them was raised against the old figure.
 */
function FactRow({
  factKey,
  field,
  caseId,
  onCorrected,
  purchase,
}: {
  factKey: string;
  field: LiveFieldValue;
  caseId: string;
  onCorrected: (detail: LiveCaseDetail) => void;
  // Set only on the first row of a second or later purchase, which is where the
  // button to remove that whole purchase belongs.
  purchase: { category: string; index: number } | null;
}) {
  const t = useTranslations("cases");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  // Two steps, because this deletes a purchase and every value describing it, and an
  // undo does not exist. A second click is cheaper than a confirmation dialogue and
  // says the same thing.
  const [confirmingRemoval, setConfirmingRemoval] = useState(false);

  async function save() {
    setSaving(true);
    setFailed(null);
    try {
      // Numbers go back as numbers: the backend validates against the question's
      // answer type, and "145" would be refused where 145 is expected.
      const parsed =
        typeof field.value === "number" && draft.trim() !== "" && !Number.isNaN(Number(draft))
          ? Number(draft)
          : draft;
      onCorrected(await correctField(caseId, factKey, parsed));
      setEditing(false);
    } catch (exc) {
      setFailed(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="px-4 py-2.5">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs text-muted-foreground">{fieldLabel(factKey, t)}</p>
          {editing ? (
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <Input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                className="h-8 max-w-[12rem]"
                aria-label={fieldLabel(factKey, t)}
                autoFocus
              />
              <Button size="sm" onClick={() => void save()} disabled={saving}>
                {t("overview.save")}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setEditing(false)} disabled={saving}>
                {t("overview.cancel")}
              </Button>
            </div>
          ) : (
            <p className="truncate text-sm">{renderValue(field.value, t)}</p>
          )}
          {field.superseded_value != null ? (
            <p className="mt-0.5 text-xs text-muted-foreground">
              {t("overview.correctedFrom", { value: String(field.superseded_value) })}
            </p>
          ) : null}
          {failed ? (
            <p role="alert" className="mt-1 text-xs text-destructive">
              {failed}
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <ProvenanceChip provenance={field.provenance} />
          {!editing ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setDraft(String(field.value ?? ""));
                setEditing(true);
              }}
            >
              {t("overview.edit")}
            </Button>
          ) : null}
        </div>
      </div>
      {editing ? (
        <p className="mt-2 text-xs text-muted-foreground">{t("overview.correctionNote")}</p>
      ) : null}

      {purchase && !editing ? (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant={confirmingRemoval ? "destructive" : "ghost"}
            disabled={saving}
            onClick={() => {
              if (!confirmingRemoval) {
                setConfirmingRemoval(true);
                return;
              }
              void removePurchase();
            }}
          >
            {confirmingRemoval
              ? t("overview.removePurchaseConfirm")
              : t("overview.removePurchase", { number: purchase.index + 1 })}
          </Button>
          {confirmingRemoval ? (
            <Button size="sm" variant="ghost" onClick={() => setConfirmingRemoval(false)}>
              {t("overview.cancel")}
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );

  async function removePurchase() {
    if (!purchase) return;
    setSaving(true);
    setFailed(null);
    try {
      onCorrected(await removeItem(caseId, purchase.category, purchase.index));
    } catch (exc) {
      setFailed(exc instanceof Error ? exc.message : String(exc));
      setConfirmingRemoval(false);
    } finally {
      setSaving(false);
    }
  }
}

export function LiveCaseOverview({ caseId }: { caseId: string }) {
  const t = useTranslations("cases");
  const { locale } = useLocale();
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

  if (error) {
    return (
      <p
        role="alert"
        className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm"
      >
        {error}
      </p>
    );
  }
  if (!detail) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24 w-full rounded-xl" />
        <Skeleton className="h-48 w-full rounded-xl" />
      </div>
    );
  }

  const fields = Object.entries(detail.fields);
  const formatLocale = locale as Parameters<typeof formatEur>[1];
  const fresh = fields.length === 0 && detail.expenses.length === 0;

  if (fresh) {
    return (
      <EmptyState
        title={t("overview.freshTitle")}
        description={t("overview.freshBody")}
        action={
          <Button asChild>
            <Link href={`/cases/${caseId}/interview`}>
              <MessagesSquare className="size-4" />
              {t("overview.startInterview")}
            </Link>
          </Button>
        }
      />
    );
  }

  return (
    <div className="space-y-8">
      {/* totals: the figure and whether itemising is worth it */}
      <section className="rounded-xl border border-border bg-surface p-5">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs text-muted-foreground">{t("overview.totalSoFar")}</p>
            <p className="mt-1 font-display text-4xl tabular-nums">
              {formatEur(detail.total_eur, formatLocale)}
            </p>
          </div>
          <div className="text-right">
            <p className="text-xs text-muted-foreground">
              <GermanTerm original={t("overview.pauschLabelOfficial")}>
                {t("overview.pauschbetrag", {
                  amount: formatEur(detail.pauschbetrag_eur, formatLocale),
                })}
              </GermanTerm>
            </p>
            <p className="mt-1 text-sm font-medium">
              {detail.total_eur > detail.pauschbetrag_eur
                ? t("overview.beatsPauschbetrag")
                : t("overview.belowPauschbetrag")}
            </p>
          </div>
        </div>
        {detail.status !== "finalized" ? (
          <Button asChild variant="outline" size="sm" className="mt-4">
            <Link href={`/cases/${caseId}/interview`}>
              {t("overview.continueInterview")}
              <ArrowRight className="size-4" />
            </Link>
          </Button>
        ) : (
          <ReopenButton
            caseId={caseId}
            onReopened={() => void getCaseDetail(caseId).then(setDetail)}
          />
        )}
      </section>

      {/* expenses, each with the trace that produced it */}
      {detail.expenses.length > 0 ? (
        <section>
          <h2 className="text-sm font-medium text-muted-foreground">
            {t("overview.expensesTitle")}
          </h2>
          <div className="mt-3 divide-y divide-border rounded-xl border border-border bg-surface">
            {detail.expenses.map((expense) => (
              <Collapsible key={`${expense.category}`}>
                <CollapsibleTrigger className="flex w-full cursor-pointer items-baseline justify-between gap-3 px-4 py-3 text-left hover:bg-accent/40">
                  <div>
                    <p className="text-sm font-medium">
                      <GermanTerm
                        original={
                          t.has(`categoriesOfficial.${expense.category}`)
                            ? t(`categoriesOfficial.${expense.category}`)
                            : ""
                        }
                      >
                        {t.has(`categories.${expense.category}`)
                          ? t(`categories.${expense.category}`)
                          : expense.category}
                      </GermanTerm>
                    </p>
                    <p className="mt-0.5 text-xs text-muted-foreground">{formLabel(expense, t)}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium tabular-nums">
                      {formatEur(expense.amount_eur, formatLocale)}
                    </span>
                    <ChevronDown className="size-4 text-muted-foreground" aria-hidden="true" />
                  </div>
                </CollapsibleTrigger>
                <CollapsibleContent className="px-4 pb-3">
                  {expense.trace.length ? (
                    <ul className="space-y-1 border-l-2 border-border pl-3 text-xs text-muted-foreground">
                      {expense.trace.map((line) => (
                        <li key={line}>{line}</li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-muted-foreground">{t("overview.sumOfReceipts")}</p>
                  )}
                </CollapsibleContent>
              </Collapsible>
            ))}
          </div>
        </section>
      ) : null}

      {/* deductions the profile points at that the case does not hold */}
      {detail.gaps.length > 0 ? (
        <section>
          <h2 className="text-sm font-medium text-muted-foreground">{t("overview.gapsTitle")}</h2>
          <div className="mt-3 space-y-2">
            {detail.gaps.map((gap) => (
              <div
                key={gap.category}
                className="rounded-lg border border-warning/50 bg-warning/10 p-3"
              >
                <p className="text-sm font-medium">
                  {t.has(`categories.${gap.category}`)
                    ? t(`categories.${gap.category}`)
                    : gap.category}
                </p>
                <p className="mt-0.5 text-sm text-muted-foreground">{gap.rationale}</p>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {/* everything the case knows, value by value, with where it came from */}
      {fields.length > 0 ? (
        <section>
          <h2 className="text-sm font-medium text-muted-foreground">{t("overview.knownTitle")}</h2>
          <div className="mt-3 divide-y divide-border rounded-xl border border-border bg-surface">
            {fields.map(([key, field], position) => {
              const purchase = purchaseOf(key);
              // The button belongs to the purchase, not to each of its fields, so it
              // appears once - on the first row of a second or later item. Removing
              // the first would leave a category whose opening purchase is numbered
              // 1, which everything that starts at zero reads as empty.
              const firstOfItem =
                purchase !== null &&
                purchase.index > 0 &&
                fields.findIndex(
                  ([other]) =>
                    purchaseOf(other)?.category === purchase.category &&
                    purchaseOf(other)?.index === purchase.index,
                ) === position;
              return (
                <FactRow
                  key={key}
                  factKey={key}
                  field={field}
                  caseId={caseId}
                  onCorrected={setDetail}
                  purchase={firstOfItem ? purchase : null}
                />
              );
            })}
          </div>
          <Separator className="mt-6" />
          <p className="mt-3 text-xs text-muted-foreground">{t("overview.provenanceNote")}</p>
        </section>
      ) : null}
    </div>
  );
}

type Translate = ReturnType<typeof useTranslations<"cases">>;

// The fact namespaces that can hold more than one purchase, and the expense category
// each belongs to. Values are keyed by what they *mean* rather than by the category
// that consumes them (#61), so `equipment.price_eur#1` is the second Arbeitsmittel and
// the removal endpoint takes the category, not the namespace.
const REPEATING: Record<string, string> = {
  equipment: "arbeitsmittel",
  education: "fortbildungskosten",
  applications: "bewerbungskosten",
};

/** The purchase a fact key belongs to, or null for anything that cannot repeat. */
function purchaseOf(key: string): { category: string; index: number } | null {
  const [namespace] = key.split(".");
  const category = REPEATING[namespace];
  if (!category) return null;
  const suffix = key.split("#")[1];
  const index = suffix ? Number(suffix) : 0;
  return Number.isFinite(index) ? { category, index } : null;
}

function fieldLabel(key: string, t: Translate): string {
  const known = `fixture.profile.${messageKey(key)}.label`;
  if (t.has(known)) return t(known);
  // A key without a prepared label still reads as words, not as an identifier.
  const bare = key.split(".").pop() ?? key;
  return bare.replaceAll("_", " ");
}

function renderValue(value: unknown, t: Translate): string {
  if (value === true) return t("interview.yes");
  if (value === false) return t("interview.no");
  return String(value);
}
