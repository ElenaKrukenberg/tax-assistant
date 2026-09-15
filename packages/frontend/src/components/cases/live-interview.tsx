"use client";

// The live interview: one pause at a time, straight from the graph.
//
// The component holds no interview logic — which question comes next, when to
// propose stopping, what counts as done all live on the backend, measured there
// (eval/). What this renders is the pause payload: a typed answer control for a
// question (ADR 0001: the catalogue's answer types, not free text), the stop
// proposal the user confirms or declines (the HITL point from the plan), the
// findings, the final gate. Refreshing the page re-requests the pending pause
// without advancing, so nothing is ever lost to a reload.

import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Feather,
  FileText,
  HelpCircle,
  Loader2,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { type AgentDebug, AgentGraphPanel } from "@/components/cases/agent-graph-panel";
import { SeverityBadge } from "@/components/cases/badges";
import { GermanTerm } from "@/components/cases/german-term";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  ApiError,
  type InterviewPause,
  type InterviewStep,
  type LiveTaxPosition,
  advanceInterview,
  advanceInterviewStream,
  listDocuments,
  stepBackInterview,
} from "@/features/cases/api";
import { formatEur } from "@/features/cases/format";
import { cn } from "@/lib/utils";
import { useLocale } from "@/i18n/locale-provider";

type Phase =
  | { kind: "loading" }
  | { kind: "pause"; step: InterviewStep }
  | { kind: "done" }
  | { kind: "error"; message: string; status: number };

// Remembered per case in the browser, not on the server: declining the offer is a
// preference about one screen, not a fact about the tax case, and a refresh should not
// put the question back. Wrapped because storage can be unavailable - a private
// window, blocked site data - and the offer showing twice is a smaller cost than a
// screen that throws.
const DOCUMENT_OFFER_KEY = "documents-offered";

function dismissedDocumentOffer(caseId: string): boolean {
  try {
    return localStorage.getItem(`${DOCUMENT_OFFER_KEY}:${caseId}`) === "1";
  } catch {
    return false;
  }
}

function dismissDocumentOffer(caseId: string): void {
  try {
    localStorage.setItem(`${DOCUMENT_OFFER_KEY}:${caseId}`, "1");
  } catch {
    // nothing to do: the offer will appear once more and that is all
  }
}

export function LiveInterview({ caseId }: { caseId: string }) {
  const t = useTranslations("cases");
  const { locale } = useLocale();
  const router = useRouter();

  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [sending, setSending] = useState(false);
  // The backend's count, not a tally kept here: a refresh used to reset the visible
  // number to zero while every answer was still in the tables (#53). Testers refresh -
  // it is the first thing anybody does when a screen looks stuck.
  const [answered, setAnswered] = useState(0);
  const [debug, setDebug] = useState<AgentDebug | null>(null);
  const [liveNode, setLiveNode] = useState<string | null>(null);
  // Shown when there is no earlier question to return to — the first one. Cleared
  // on the next move, so it never lingers over a question it does not describe.
  const [backBlocked, setBackBlocked] = useState(false);
  // Whether to offer documents before the first question. Null while we are still
  // asking the case what it holds - rendering the offer and then withdrawing it would
  // be worse than a moment of nothing.
  const [offerDocuments, setOfferDocuments] = useState<boolean | null>(null);

  const apply = useCallback((step: InterviewStep) => {
    setDebug(step.debug ?? null);
    setAnswered(step.answered ?? 0);
    setPhase(step.done ? { kind: "done" } : { kind: "pause", step });
  }, []);

  // The offer is worth making exactly once, before anything has been answered.
  // A value read out of a document removes its own question - `relevant_questions`
  // drops anything the case already knows, whatever it came from - so uploading
  // first is strictly less work for the user. Nothing about that is visible unless
  // somebody says it, which is the whole of this screen.
  useEffect(() => {
    let live = true;
    listDocuments(caseId)
      .then((documents) => {
        if (!live) return;
        const has = documents.some((d) => d.state === "confirmed");
        setOfferDocuments(!has && !dismissedDocumentOffer(caseId));
      })
      // A case whose documents cannot be listed is not a case to block: the
      // interview is the thing the user came for.
      .catch(() => live && setOfferDocuments(false));
    return () => {
      live = false;
    };
  }, [caseId]);

  useEffect(() => {
    // Reconnect to whatever the graph is waiting on; undefined resume never advances.
    advanceInterview(caseId)
      .then(apply)
      .catch((exc) => {
        if (exc instanceof ApiError && exc.status === 401) {
          router.replace("/login");
          return;
        }
        setPhase({
          kind: "error",
          message: exc instanceof Error ? exc.message : String(exc),
          status: exc instanceof ApiError ? exc.status : 0,
        });
      });
  }, [caseId, apply, router]);

  async function goBack() {
    setSending(true);
    setBackBlocked(false);
    try {
      const step = await stepBackInterview(caseId);
      apply(step);
    } catch (exc) {
      // 409 is not a failure: it is the first question, and there is nothing behind
      // it. Anything else is a real error and belongs on the error screen.
      if (exc instanceof ApiError && exc.status === 409) {
        setBackBlocked(true);
      } else {
        setPhase({
          kind: "error",
          message: exc instanceof Error ? exc.message : String(exc),
          status: exc instanceof ApiError ? exc.status : 0,
        });
      }
    } finally {
      setSending(false);
    }
  }

  async function send(resume: unknown) {
    setSending(true);
    setBackBlocked(false);
    setLiveNode(null);
    try {
      const step = await advanceInterviewStream(caseId, resume, setLiveNode);
      apply(step);
    } catch (exc) {
      setPhase({
        kind: "error",
        message: exc instanceof Error ? exc.message : String(exc),
        status: exc instanceof ApiError ? exc.status : 0,
      });
    } finally {
      setSending(false);
      setLiveNode(null);
    }
  }

  if (phase.kind === "loading") {
    return (
      <div className="mx-auto w-full max-w-2xl space-y-4">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-40 w-full rounded-xl" />
      </div>
    );
  }

  if (phase.kind === "error") {
    return (
      <div className="mx-auto w-full max-w-2xl rounded-xl border border-destructive/40 bg-destructive/10 p-6">
        <AlertTriangle className="size-5 text-destructive" aria-hidden="true" />
        <p role="alert" className="mt-2 text-sm">
          {phase.message}
        </p>
        <Button variant="outline" className="mt-4" onClick={() => window.location.reload()}>
          {t("interview.retry")}
        </Button>
      </div>
    );
  }

  if (phase.kind === "done") {
    return (
      <section className="mx-auto w-full max-w-2xl rounded-xl border border-border bg-surface p-6">
        <CheckCircle2 className="size-6 text-success" aria-hidden="true" />
        <h1 className="mt-3 font-display text-3xl leading-tight">{t("interview.liveDoneTitle")}</h1>
        <p className="mt-2 text-sm text-muted-foreground">{t("interview.finalizedBody")}</p>
        <Button asChild className="mt-6">
          <Link href={`/cases/${caseId}`}>
            {t("interview.backToCase")}
            <ArrowRight className="size-4" />
          </Link>
        </Button>
        <AgentGraphPanel debug={debug} busy={false} />
      </section>
    );
  }

  // Only before the first answer. Somebody who has already started does not need to
  // be sent somewhere else, and `answered` is the tables' own count, so a refresh
  // mid-interview cannot resurrect the offer (#53).
  if (offerDocuments && answered === 0) {
    return (
      <section className="mx-auto w-full max-w-2xl rounded-xl border border-border bg-surface p-6">
        <FileText className="size-6 text-primary" aria-hidden="true" />
        <h1 className="mt-3 font-display text-2xl leading-tight">
          {t("interview.documentsFirstTitle")}
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">{t("interview.documentsFirstBody")}</p>
        <div className="mt-6 flex flex-wrap gap-2">
          <Button asChild>
            <Link href={`/cases/${caseId}/documents`}>
              <FileText className="size-4" />
              {t("interview.documentsFirstUpload")}
            </Link>
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              dismissDocumentOffer(caseId);
              setOfferDocuments(false);
            }}
          >
            {t("interview.documentsFirstSkip")}
          </Button>
        </div>
        <p className="mt-4 text-xs text-muted-foreground">{t("interview.documentsFirstLater")}</p>
      </section>
    );
  }

  const pause = phase.step.pause!;
  return (
    <div className="mx-auto w-full max-w-2xl">
      <p className="text-xs text-muted-foreground">{t("interview.honestProgress", { answered })}</p>
      {/* At the top of the interview rather than beside the disclaimer at the bottom:
          the first question is the first AI interaction, and a disclosure under it has
          already missed (#87). It also draws the line #89 cares about - the model picks
          the questions, the arithmetic is not the model's. */}
      <p className="mt-2 text-xs text-muted-foreground">{t("interview.aiDisclosure")}</p>
      <div className="mt-6">
        {sending ? (
          <AgentWriting liveNode={liveNode} />
        ) : pause.type === "question" ? (
          <QuestionCard pause={pause} locale={locale} sending={sending} onAnswer={send} />
        ) : pause.type === "confirm_stop" ? (
          <ConfirmStopCard pause={pause} locale={locale} sending={sending} onResolve={send} />
        ) : pause.type === "findings" ? (
          <FindingsCard pause={pause} sending={sending} onResolve={send} />
        ) : (
          <FinalApprovalCard pause={pause} locale={locale} sending={sending} onResolve={send} />
        )}
      </div>
      {!sending && (pause.type === "question" || pause.type === "confirm_stop") ? (
        <div className="mt-3 flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={() => void goBack()} disabled={sending}>
            <ArrowLeft className="size-4" />
            {t("interview.back")}
          </Button>
          {backBlocked ? (
            <p className="text-xs text-muted-foreground">{t("interview.backNothing")}</p>
          ) : null}
        </div>
      ) : null}
      <AgentGraphPanel debug={debug} busy={sending} liveNode={liveNode} />
    </div>
  );
}

// Which node of the graph the wait is currently in. The SSE stream reports each one
// as it is crossed, so the line under the quill is what is actually happening rather
// than a hopeful guess — and when the stream is unavailable it falls back to the one
// thing always true of an advance: the Interviewer is deciding.
const WAITING_ON: Record<string, string> = {
  decide_next: "waitingDeciding",
  ask_user: "waitingWriting",
  confirm_stop: "waitingDeciding",
  build_expenses: "waitingCalculating",
  review: "waitingReviewing",
  resolve_findings: "waitingReviewing",
  final_approval: "waitingCalculating",
};

function QuillWriting() {
  return (
    // The nib of lucide's feather sits at its bottom-left, which is what makes the
    // trick work: the icon slides right, the line draws under it, and the two share
    // one timing so the ink always ends where the nib is.
    <div className="relative h-14 w-28" aria-hidden="true">
      <svg viewBox="0 0 112 56" className="absolute inset-0 size-full text-primary" fill="none">
        <path
          className="quill-ink"
          d="M22 47h64"
          stroke="currentColor"
          strokeWidth="1.75"
          strokeLinecap="round"
          opacity="0.4"
        />
      </svg>
      <Feather className="quill-pen absolute left-3 top-1 size-10 text-primary" strokeWidth={1.5} />
    </div>
  );
}

function AgentWriting({ liveNode }: { liveNode: string | null }) {
  const t = useTranslations("cases");
  const key = (liveNode && WAITING_ON[liveNode]) || "waitingDeciding";
  return (
    <section
      className="rounded-xl border border-border bg-surface p-8"
      aria-live="polite"
      aria-busy="true"
    >
      <div className="flex flex-col items-center text-center">
        <QuillWriting />
        <p className="mt-3 text-base font-medium">{t(`interview.${key}`)}</p>
        <p className="mt-1 text-sm text-muted-foreground">{t("interview.waitingHint")}</p>
      </div>
    </section>
  );
}

function QuestionCard({
  pause,
  locale,
  sending,
  onAnswer,
}: {
  pause: InterviewPause;
  locale: string;
  sending: boolean;
  onAnswer: (resume: unknown) => Promise<void>;
}) {
  const t = useTranslations("cases");
  const [raw, setRaw] = useState("");

  // The catalogue carries en/de/ru; tr falls back to en with the existing note.
  const text = pause.text?.[locale] ?? pause.text?.en ?? "";
  // The question catalogue is not translated into every offered language, and a
  // silent fallback reads as "this product speaks your language" when it does not.
  // Said per question rather than once per session: only some of them fall back.
  const inEnglish = locale !== "en" && !pause.text?.[locale] && Boolean(pause.text?.en);
  const type = pause.answer_type ?? "text";

  // Reset the control when the question changes, not the component.
  useEffect(() => setRaw(""), [pause.question_id]);

  function submit() {
    let value: unknown = raw;
    if (type === "integer" || type === "month" || type === "percent") value = Number(raw);
    if (type === "money") value = Number(raw);
    void onAnswer({ value });
  }

  const numeric = ["integer", "money", "percent", "month"].includes(type);

  return (
    <section className="rounded-xl border border-border bg-surface p-6">
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        {pause.category && t.has(`categories.${pause.category}`)
          ? t(`categories.${pause.category}`)
          : t("interview.aboutYou")}
        {/* Only when there is a second one. Numbering the first purchase "Purchase 1"
            would imply more are coming before anybody has said so (#35). */}
        {pause.item_index ? (
          <span className="ml-2 normal-case text-muted-foreground">
            · {t("interview.purchaseNumber", { number: pause.item_index + 1 })}
          </span>
        ) : null}
      </p>
      {pause.rationale ? (
        <p className="mt-2 text-sm text-muted-foreground">{pause.rationale}</p>
      ) : null}
      <h1 className="mt-2 text-2xl font-medium leading-snug" lang={inEnglish ? "en" : locale}>
        {text}
      </h1>
      {inEnglish ? (
        <p className="mt-1 text-xs text-muted-foreground">{t("interview.shownInEnglish")}</p>
      ) : null}

      <div className="mt-6">
        {type === "boolean" ? (
          <ToggleGroup
            type="single"
            className="justify-start"
            onValueChange={(v) => v && void onAnswer({ value: v === "yes" })}
          >
            <ToggleGroupItem value="yes" disabled={sending}>
              {t("interview.yes")}
            </ToggleGroupItem>
            <ToggleGroupItem value="no" disabled={sending}>
              {t("interview.no")}
            </ToggleGroupItem>
          </ToggleGroup>
        ) : type === "choice" ? (
          <Select onValueChange={(v) => void onAnswer({ value: v })} disabled={sending}>
            <SelectTrigger className="w-full max-w-sm">
              <SelectValue placeholder={t("interview.choose")} />
            </SelectTrigger>
            <SelectContent>
              {(pause.options ?? []).map((option) => (
                <SelectItem key={option} value={option}>
                  {t.has(`interview.options.${option}`) ? t(`interview.options.${option}`) : option}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <form
            className="flex max-w-sm items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (raw !== "") submit();
            }}
          >
            <div className="flex-1">
              <Label htmlFor="answer" className="text-xs text-muted-foreground">
                {type === "money" ? t("interview.amountEur") : t("interview.value")}
              </Label>
              <Input
                id="answer"
                autoFocus
                inputMode={numeric ? "decimal" : undefined}
                type={type === "date" ? "date" : numeric ? "number" : "text"}
                min={pause.minimum ?? undefined}
                max={pause.maximum ?? undefined}
                step={type === "money" ? "0.01" : undefined}
                value={raw}
                onChange={(e) => setRaw(e.target.value)}
                disabled={sending}
              />
            </div>
            <Button type="submit" disabled={sending || raw === ""}>
              {sending ? <Loader2 className="size-4 animate-spin" /> : null}
              {t("interview.answer")}
            </Button>
          </form>
        )}
      </div>

      <button
        type="button"
        className="mt-6 inline-flex items-center gap-1.5 text-sm text-muted-foreground underline-offset-4 hover:underline"
        disabled={sending}
        onClick={() => void onAnswer({ value: null })}
      >
        <HelpCircle className="size-4" aria-hidden="true" />
        {t("interview.dontKnow")}
      </button>
    </section>
  );
}

function ConfirmStopCard({
  pause,
  locale,
  sending,
  onResolve,
}: {
  pause: InterviewPause;
  locale: string;
  sending: boolean;
  onResolve: (resume: unknown) => Promise<void>;
}) {
  const t = useTranslations("cases");
  const carried = pause.carried_over ?? [];
  // Keys the user says are no longer true. Rejecting one reopens the interview and
  // the question is asked again, so this is a correction, not a veto on stopping.
  const [rejected, setRejected] = useState<string[]>([]);

  function toggle(key: string) {
    setRejected((keys) => (keys.includes(key) ? keys.filter((k) => k !== key) : [...keys, key]));
  }

  function show(value: unknown, answerType: string) {
    if (answerType === "boolean") return value ? t("interview.yes") : t("interview.no");
    return String(value);
  }

  return (
    <section className="rounded-xl border border-border bg-surface p-6">
      <h1 className="font-display text-2xl leading-tight">
        {pause.escalated ? t("interview.escalatedTitle") : t("interview.stopTitle")}
      </h1>
      <p className="mt-2 text-sm text-muted-foreground">{pause.reason}</p>
      {(pause.gaps ?? []).length > 0 ? (
        <div className="mt-4 rounded-lg border border-warning/50 bg-warning/10 p-3">
          <p className="text-sm font-medium">{t("interview.gapsTitle")}</p>
          <ul className="mt-2 space-y-3">
            {(pause.gaps ?? []).map((gap) => (
              <li key={gap.category}>
                <p className="text-sm font-medium">
                  {t.has(`categories.${gap.category}`)
                    ? t(`categories.${gap.category}`)
                    : gap.category}
                </p>
                <p className="mt-0.5 text-sm text-muted-foreground">{gap.rationale}</p>
                {gap.citation_quote ? (
                  <blockquote className="mt-1.5 border-l-2 border-warning/60 pl-2 text-xs italic text-muted-foreground">
                    {gap.citation_quote}
                    {gap.citation_title ? (
                      <span className="not-italic"> — {gap.citation_title}</span>
                    ) : null}
                  </blockquote>
                ) : null}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-muted-foreground">{t("interview.gapsHint")}</p>
        </div>
      ) : null}
      {carried.length > 0 ? (
        <div className="mt-4 rounded-lg border border-border bg-surface-2 p-3">
          <p className="text-sm font-medium">{t("interview.carriedTitle")}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">{t("interview.carriedHint")}</p>
          <ul className="mt-3 space-y-3">
            {carried.map((item) => (
              <li key={item.key} className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm">{item.text?.[locale] ?? item.text?.en ?? item.key}</p>
                  <p className="mt-0.5 text-sm font-medium">{show(item.value, item.answer_type)}</p>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant={rejected.includes(item.key) ? "default" : "outline"}
                  aria-pressed={rejected.includes(item.key)}
                  disabled={sending}
                  onClick={() => toggle(item.key)}
                >
                  {rejected.includes(item.key)
                    ? t("interview.carriedWillAsk")
                    : t("interview.carriedChanged")}
                </Button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="mt-6 flex flex-wrap gap-2">
        <Button
          onClick={() => void onResolve({ confirm: true, reject: rejected })}
          disabled={sending}
        >
          {sending ? <Loader2 className="size-4 animate-spin" /> : null}
          {rejected.length > 0 ? t("interview.stopAcceptWithChanges") : t("interview.stopAccept")}
        </Button>
        <Button
          variant="outline"
          onClick={() => void onResolve({ confirm: false, reject: rejected })}
          disabled={sending}
        >
          {t("interview.stopDecline")}
        </Button>
      </div>
    </section>
  );
}

function FindingsCard({
  pause,
  sending,
  onResolve,
}: {
  pause: InterviewPause;
  sending: boolean;
  onResolve: (resume: unknown) => Promise<void>;
}) {
  const t = useTranslations("cases");
  return (
    <section className="rounded-xl border border-border bg-surface p-6">
      <h1 className="font-display text-2xl leading-tight">{t("interview.findingsTitle")}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{t("interview.findingsBody")}</p>
      <ul className="mt-4 space-y-3">
        {(pause.findings ?? []).map((finding) => (
          <li key={finding.title} className="rounded-lg border border-border p-3">
            <div className="flex items-center gap-2">
              <SeverityBadge severity={toSeverity(finding.severity)} />
              <p className="text-sm font-medium">{finding.title}</p>
            </div>
            <p className="mt-1.5 text-sm text-muted-foreground">{finding.reasoning}</p>
          </li>
        ))}
      </ul>
      <div className="mt-6 flex flex-wrap gap-2">
        <Button onClick={() => void onResolve({ action: "revise" })} disabled={sending}>
          {t("interview.revise")}
        </Button>
        <Button
          variant="outline"
          onClick={() => void onResolve({ action: "dismiss" })}
          disabled={sending}
        >
          {t("interview.dismissFindings")}
        </Button>
      </div>
    </section>
  );
}

/**
 * One proposed tax position, and the three answers a person can give it.
 *
 * Three and not two (#77): "not sure" is a real answer, and without it the only way
 * to express it is to leave the card alone, which looks the same as not having read
 * it. It clears the choice rather than storing a fourth state - undecided already
 * means "not in the draft, question still open", and it keeps Approve disabled.
 *
 * The card also has to say who produced the figure (#89). Printing `origin` was
 * technically an answer and practically none: a person reading `deterministic_rule`
 * in grey learns nothing. What matters to them is the distinction the enum encodes -
 * the arithmetic is not a model's, even when a model read one of the numbers off a
 * document and they confirmed it themselves.
 */
function PositionCard({
  position,
  decision,
  formula,
  locale,
  onDecide,
}: {
  position: LiveTaxPosition;
  decision: "accepted" | "rejected" | undefined;
  // The first line of the expense's trace - "220 days x 12 km x 0.30 EUR/km". It
  // used to live in a separate list above these cards, which printed every category
  // twice: once as a figure and again as a decision. One card per position now, and
  // the formula belongs on the card whose figure it explains.
  formula: string | undefined;
  locale: string;
  onDecide: (next: "accepted" | "rejected" | null) => void;
}) {
  const t = useTranslations("cases");
  const formatLocale = locale as Parameters<typeof formatEur>[1];
  const label = t.has(`categories.${position.category}`)
    ? t(`categories.${position.category}`)
    : position.category;
  // The official German name travels with the translation everywhere a category is
  // named, because that is the word on the form and in any letter about it.
  const official = t.has(`categoriesOfficial.${position.category}`)
    ? t(`categoriesOfficial.${position.category}`)
    : "";
  // A model transcribing a number off a document is not a model proposing a figure,
  // and the card must not let the first pass for the second.
  const readByModel = position.provenance.some((entry) => entry.origin === "ai_inference");
  const proposedByModel = position.provenance.some((entry) => entry.origin === "ai_suggestion");

  return (
    // The card carries the state, because the buttons could not: three of them side
    // by side read as a switch with one option already chosen, so an untouched
    // position looked answered. The border and the badge say which of the three
    // states this position is actually in, before the buttons are read at all.
    <div
      id={`position-${position.position_id}`}
      className={cn(
        "rounded-lg border p-3 transition-colors",
        decision === undefined
          ? "border-warning/60 bg-warning/5"
          : decision === "rejected"
            ? "border-border bg-muted/30"
            : "border-success/50 bg-success/5",
      )}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-medium">
          <GermanTerm original={official}>{label}</GermanTerm>
        </p>
        {position.proposed_amount != null ? (
          <p
            className={cn(
              "text-sm tabular-nums",
              decision === "rejected" ? "text-muted-foreground line-through" : "",
            )}
          >
            {formatEur(position.proposed_amount, formatLocale)}
          </p>
        ) : null}
      </div>

      <p
        className={cn(
          "mt-1 text-xs font-medium",
          // The token, not its -foreground pair: those are for text sitting on the
          // colour, and this text sits on the card.
          decision === undefined
            ? "text-warning"
            : decision === "rejected"
              ? "text-muted-foreground"
              : "text-success",
        )}
      >
        {decision === undefined
          ? t("positions.stateUndecided")
          : decision === "rejected"
            ? t("positions.stateRejected")
            : t("positions.stateAccepted")}
      </p>

      {formula ? <p className="mt-1 text-xs text-muted-foreground">{formula}</p> : null}

      <p className="mt-1 text-xs text-muted-foreground">
        {proposedByModel ? t("positions.proposedByModel") : t("positions.calculated")}
        {readByModel ? ` ${t("positions.readFromDocument")}` : ""}
      </p>

      {position.source_refs.length > 0 ? (
        <details className="mt-2">
          <summary className="cursor-pointer text-xs text-muted-foreground underline-offset-2 hover:underline">
            {t("positions.whyProposed")}
          </summary>
          <div className="mt-2 space-y-2">
            {position.source_refs.map((citation) => (
              <figure key={citation.rule_id} className="border-l-2 border-primary/50 pl-3">
                {/* German and unabridged: it is the text of the law, and a shortened
                    one would be our wording presented as the Finanzamt's. */}
                <blockquote className="text-xs italic leading-relaxed" lang="de">
                  {citation.excerpt}
                </blockquote>
                <figcaption className="mt-1 text-[11px] text-muted-foreground">
                  {citation.reference}
                </figcaption>
              </figure>
            ))}
          </div>
        </details>
      ) : null}

      {/* The question the buttons answer, written out. Without it the row was three
          verbs with no sentence above them, and a person cannot tell a choice they
          must make from a setting that already has a value. */}
      <p className="mt-3 text-sm">
        {position.proposed_amount != null
          ? t("positions.question", {
              amount: formatEur(position.proposed_amount, formatLocale),
            })
          : t("positions.questionNoAmount")}
      </p>

      <div className="mt-2 flex flex-wrap gap-2">
        <Button
          size="sm"
          variant={decision === "accepted" ? "default" : "outline"}
          aria-pressed={decision === "accepted"}
          onClick={() => onDecide("accepted")}
        >
          {t("positions.add")}
        </Button>
        <Button
          size="sm"
          variant={decision === "rejected" ? "default" : "outline"}
          aria-pressed={decision === "rejected"}
          onClick={() => onDecide("rejected")}
        >
          {t("positions.doNotAdd")}
        </Button>
      </div>

      {/* "Not sure" is a real answer (#77) and not a third equal option: it leaves
          the question open, which is the one state that cannot finish a return. As a
          button of the same weight it was indistinguishable from an answer; as a
          link under the two answers it is what it is - a way to take a choice back. */}
      {decision !== undefined ? (
        <button
          type="button"
          onClick={() => onDecide(null)}
          className="mt-2 cursor-pointer text-xs text-muted-foreground underline-offset-2 hover:underline"
        >
          {t("positions.notSure")}
        </button>
      ) : (
        <p className="mt-2 text-xs text-muted-foreground">{t("positions.notSureHint")}</p>
      )}
    </div>
  );
}

function FinalApprovalCard({
  pause,
  locale,
  sending,
  onResolve,
}: {
  pause: InterviewPause;
  locale: string;
  sending: boolean;
  onResolve: (resume: unknown) => Promise<void>;
}) {
  const t = useTranslations("cases");
  const expenses = pause.expenses ?? [];
  const positions = pause.tax_positions ?? [];
  const [decisions, setDecisions] = useState<Record<string, "accepted" | "rejected">>(
    () =>
      Object.fromEntries(
        positions
          .filter(
            (position) =>
              position.user_decision === "accepted" || position.user_decision === "rejected",
          )
          .map((position) => [position.position_id, position.user_decision]),
      ) as Record<string, "accepted" | "rejected">,
  );
  const formatLocale = locale as Parameters<typeof formatEur>[1];
  // The formula belongs beside the figure it explains, and the figure is on the
  // card. Keyed by category because that is what an expense row and a position
  // share; a category with several purchases still has one calculation to show.
  const formulaOf = new Map(
    expenses.map((expense) => [expense.category, expense.trace[0]] as const),
  );
  const decidable = positions.filter(
    (position) => position.assessment_status !== "criteria_not_met",
  );
  const undecided = decidable.filter((position) => !decisions[position.position_id]);
  // Which position the last click on the finish button pointed at, so the reason
  // under it is announced rather than sitting there as static grey text.
  const [nudge, setNudge] = useState<string | null>(null);
  // The total follows the decisions on screen rather than the expenses the graph
  // built: a figure the user has just declined is not part of what they are about
  // to approve, and a sum that says otherwise is the screen contradicting itself.
  const total = decidable
    .filter((position) => decisions[position.position_id] === "accepted")
    .reduce((sum, position) => sum + (position.proposed_amount ?? 0), 0);

  return (
    <section className="rounded-xl border border-border bg-surface p-6">
      <h1 className="font-display text-2xl leading-tight">{t("interview.approveTitle")}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{t("interview.approveBody")}</p>

      {/* How much of the work is done, said once at the top. A list of cards gives no
          sense of how many answers are still owed, and the disabled button at the
          bottom was the first place that ever mentioned it. */}
      <p className="mt-3 text-sm font-medium" aria-live="polite">
        {t("interview.decidedCount", {
          decided: decidable.length - undecided.length,
          total: decidable.length,
        })}
      </p>

      <div className="mt-4 space-y-3">
        {decidable.map((position: LiveTaxPosition) => (
          <PositionCard
            key={position.position_id}
            position={position}
            decision={decisions[position.position_id]}
            formula={formulaOf.get(position.category)}
            locale={locale}
            onDecide={(next) =>
              setDecisions((current) => {
                // "Not sure" clears the choice rather than storing a fourth state.
                // Undecided is already a state the backend has, and it is the one
                // that means what the button means: not in the draft, question
                // still open. It also keeps Approve disabled, which is the point -
                // a return should not be filed on a figure nobody decided.
                const { [position.position_id]: _removed, ...rest } = current;
                return next === null ? rest : { ...rest, [position.position_id]: next };
              })
            }
          />
        ))}
      </div>

      <p className="mt-4 text-right text-sm font-medium tabular-nums">
        {t("interview.total")}: {formatEur(total, formatLocale)}
      </p>
      <p className="mt-4 text-xs text-muted-foreground">{t("interview.disclaimer")}</p>
      <div className="mt-4 flex flex-wrap gap-2">
        {/* Not disabled while anything is undecided. A grey button is a dead end: it
            states a rule nobody asked about and gives no way to satisfy it. This one
            answers - it takes the user to the first position still waiting, and says
            so - and finalizes only when there is nothing left to answer. */}
        <Button
          onClick={() => {
            if (undecided.length > 0) {
              const first = undecided[0];
              setNudge(first.position_id);
              document
                .getElementById(`position-${first.position_id}`)
                ?.scrollIntoView({ behavior: "smooth", block: "center" });
              return;
            }
            void onResolve({ approve: true, decisions });
          }}
          disabled={sending}
        >
          {sending ? <Loader2 className="size-4 animate-spin" /> : null}
          {undecided.length > 0 ? t("interview.approveShowFirst") : t("interview.approve")}
        </Button>
        <Button
          variant="outline"
          onClick={() => void onResolve({ approve: false, decisions })}
          disabled={sending}
        >
          {t("interview.backToQuestions")}
        </Button>
      </div>
      {undecided.length > 0 ? (
        <p className="mt-2 text-xs text-muted-foreground" role={nudge ? "alert" : undefined}>
          {t("interview.approveBlocked", { count: undecided.length })}
        </p>
      ) : null}
      {/* Said before the click, not after it: approving locks the case, and the way
          back is a button on the report rather than something to discover. */}
      <p className="mt-2 text-xs text-muted-foreground">{t("interview.approveLocks")}</p>
    </section>
  );
}

function toSeverity(value: string): "blocking" | "warning" | "suggestion" {
  return value === "blocking" || value === "suggestion" ? value : "warning";
}
