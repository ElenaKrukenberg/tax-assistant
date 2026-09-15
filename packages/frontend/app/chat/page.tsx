"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useLocale } from "@/i18n/locale-provider";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { AppNav } from "@/components/gta/app-nav";
import { BackendStatusBanner } from "@/components/gta/backend-status-banner";
import { PromptBox } from "@/components/gta/prompt-box";
import { ClarificationBanner, ToolResultCard } from "@/components/gta/result-cards";
import { Button } from "@/components/ui/button";
import type { TaxAnswer, Source } from "@tax-assistant/shared/types";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  downloadFile,
  exportFilename,
  toJson,
  toMarkdown,
  type ExportConversation,
} from "@/lib/conversation-export";
import {
  buildHistory,
  conversationTitle,
  deserializeMessages,
  errorAnswer,
  formatWhen,
  loadConversations,
  memoryBoundary,
  persistConversations,
  serializeMessages,
  toAnswer,
  type Answer,
  type Conversation,
  type Message,
  type TraceStep,
} from "@/lib/conversation-history";
import { getAnswersFollowUi, getDepth } from "@/lib/preferences";
import { useSaveHistory, useShowTrace } from "@/hooks/use-preferences";
import { cn } from "@/lib/utils";
import { Fragment, Suspense, useEffect, useMemo, useRef, useState } from "react";
import {
  Plus,
  MessageSquare,
  Copy,
  RefreshCw,
  ThumbsUp,
  ThumbsDown,
  ExternalLink,
  ShieldCheck,
  Sparkles,
  ChevronDown,
  BrainCircuit,
  CheckCircle2,
  Coins,
  History,
  Download,
  X,
} from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function ChatPage() {
  // useSearchParams() must live under a Suspense boundary for prerendering
  return (
    <Suspense>
      <ChatPageInner />
    </Suspense>
  );
}

function ChatPageInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const t = useTranslations("chat");
  const tNav = useTranslations("nav");
  const { locale } = useLocale();
  const q = searchParams.get("q");
  const [messages, setMessages] = useState<Message[]>([]);
  const [phase, setPhase] = useState<"idle" | "thinking">("idle");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState(() => crypto.randomUUID());

  // Off means off: no reading what is stored and no writing more. Switching it off
  // in Settings is what clears what was already there, so there is nothing here to
  // clean up - this only stops the page putting it back.
  const saveHistory = useSaveHistory();

  // load history once on mount (localStorage is client-only)
  useEffect(() => {
    if (!saveHistory) return;
    setConversations(loadConversations());
  }, [saveHistory]);

  // auto-save the active conversation on every message change
  useEffect(() => {
    if (!saveHistory) return;
    if (messages.length === 0) return;
    const title = conversationTitle(messages);
    setConversations((prev) => {
      const rest = prev.filter((c) => c.id !== conversationId);
      const updated: Conversation[] = [
        { id: conversationId, title, updatedAt: Date.now(), messages: serializeMessages(messages) },
        ...rest,
      ];
      persistConversations(updated);
      return updated;
    });
  }, [messages, conversationId, saveHistory]);

  // A question in flight belongs to the conversation that asked it. Leaving that
  // conversation abandons the request: without this the reply arrives into whatever
  // transcript is on screen — a brand-new chat showing an answer to a question that
  // is no longer there, and stuck on "thinking" until the old request settles.
  const inFlight = useRef<AbortController | null>(null);

  function abandonInFlight() {
    inFlight.current?.abort();
    inFlight.current = null;
    setPhase("idle");
  }

  function newConversation() {
    abandonInFlight();
    setMessages([]);
    setConversationId(crypto.randomUUID());
  }

  function openConversation(c: Conversation) {
    abandonInFlight();
    setMessages(deserializeMessages(c.messages));
    setConversationId(c.id);
  }

  // Exported from the stored form rather than from `messages`: the icon components
  // attached for rendering are not serializable, and the stored shape is the one a
  // re-import would have to read. The file never leaves the browser.
  function exportConversation(format: "md" | "json") {
    const now = Date.now();
    const conversation: ExportConversation = {
      id: conversationId,
      title: conversationTitle(messages),
      updatedAt: now,
      messages: serializeMessages(messages),
    };
    if (format === "json") {
      downloadFile(
        exportFilename(conversation, "json"),
        "application/json",
        toJson(conversation, now),
      );
      return;
    }
    downloadFile(
      exportFilename(conversation, "md"),
      "text/markdown",
      toMarkdown(
        conversation,
        {
          appName: tNav("appName"),
          assistantName: t("assistantName"),
          you: t("you"),
          exported: t("exported"),
          explanation: t("explanation"),
          sources: t("sources"),
          warnings: t("warnings"),
          disclaimer: t("disclaimer"),
          requestId: t("detailsRequestId"),
          model: t("detailsModel"),
        },
        now,
      ),
    );
  }

  function deleteConversation(id: string) {
    setConversations((prev) => {
      const updated = prev.filter((c) => c.id !== id);
      persistConversations(updated);
      return updated;
    });
    if (id === conversationId) newConversation();
  }

  // addUserBubble=false is used by "Regenerate": re-runs the question
  // without duplicating the user's bubble. historyEnd is where the replayed
  // conversation stops — for a regenerate that is the index of the question being
  // re-asked, so the stale answer below it is not sent back as context.
  async function ask(text: string, addUserBubble = true, historyEnd?: number) {
    if (addUserBubble) {
      const userMsg: Message = { id: crypto.randomUUID(), role: "user", text };
      setMessages((m) => [...m, userMsg]);
    }
    // one question at a time: a new ask supersedes an earlier unanswered one
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;
    setPhase("thinking");
    try {
      const res = await fetch(`${API_URL}/api/v1/tax/ask`, {
        method: "POST",
        signal: controller.signal,
        headers: { "Content-Type": "application/json" },
        // "auto" = answer in the question's language; the Settings toggle
        // switches to the interface language instead
        body: JSON.stringify({
          text,
          language: getAnswersFollowUi() ? locale : "auto",
          // How much answer the user asked for, from the same Settings screen.
          depth: getDepth(),
          // the API is stateless, so a follow-up like "74 km" is only answerable
          // if the earlier turns travel with it
          history: buildHistory(messages, historyEnd),
        }),
      });
      // The API caps /ask per client and globally, because every question costs a
      // provider call. Nothing here is broken and nothing the user can check, so it
      // gets its own message instead of the generic "is the backend running?" one.
      if (res.status === 429) {
        const wait = Number(res.headers.get("Retry-After")) || 60;
        setMessages((m) => [
          ...m,
          {
            id: crypto.randomUUID(),
            role: "assistant",
            answer: errorAnswer(
              `HTTP 429, Retry-After: ${wait}s`,
              t("rateLimited", { seconds: wait }),
            ),
          },
        ]);
        return;
      }
      if (!res.ok) throw new Error(`API responded with HTTP ${res.status}`);
      const data = await res.json();
      setMessages((m) => [
        ...m,
        { id: crypto.randomUUID(), role: "assistant", answer: toAnswer(data) },
      ]);
    } catch (e) {
      // abandoned on purpose (conversation switched, or superseded): the answer is
      // no longer wanted, and it is not a failure to report
      if (controller.signal.aborted) return;
      const detail =
        e instanceof TypeError
          ? `network/CORS error reaching ${API_URL} (is the backend running? does CORS allow this origin?)`
          : e instanceof Error
            ? e.message
            : String(e);
      setMessages((m) => [
        ...m,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          answer: errorAnswer(detail, t("errorSummary")),
        },
      ]);
    } finally {
      // only the newest request owns the phase; a stale one must not clear it
      if (inFlight.current === controller) {
        inFlight.current = null;
        setPhase("idle");
      }
    }
  }

  const boundaryIdx = memoryBoundary(messages);

  // Regenerate re-asks the question above this answer, replaying only what came
  // before it — so the answer being regenerated is not fed back as its own context.
  function regenerateHandler(answerIdx: number): (() => void) | undefined {
    const questionIdx = messages
      .slice(0, answerIdx)
      .map((x, i) => (x.role === "user" ? i : -1))
      .reduce((last, i) => (i >= 0 ? i : last), -1);
    const question = questionIdx >= 0 ? messages[questionIdx] : undefined;
    if (!question || question.role !== "user") return undefined;
    return () => ask(question.text, false, questionIdx);
  }

  // useRef guard: React StrictMode double-invokes effects in dev, and the
  // messages.length check can't see the first invocation's state update yet —
  // that caused duplicated question + answer when arriving from the landing page.
  const askedFromUrl = useRef(false);
  useEffect(() => {
    if (askedFromUrl.current) return;
    // primary handoff: sessionStorage (set by the landing page — no URL flash);
    // ?q= stays supported as a fallback for direct/shared links
    const pending = sessionStorage.getItem("pending-question");
    const question = pending ?? q;
    if (!question) return;
    askedFromUrl.current = true;
    if (pending) sessionStorage.removeItem("pending-question");
    ask(question);
    if (q) router.replace("/chat", { scroll: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  return (
    <div className="min-h-dvh bg-background">
      <AppNav />

      <div className="mx-auto flex max-w-7xl">
        {/* Sidebar */}
        <aside className="sticky top-14 hidden h-[calc(100dvh-3.5rem)] w-64 shrink-0 border-r border-border bg-sidebar px-3 py-4 md:block">
          <Button
            variant="outline"
            className="w-full justify-start gap-2 border-border bg-surface font-medium"
            onClick={newConversation}
          >
            <Plus className="h-4 w-4" />
            {t("newConversation")}
          </Button>

          {/* Nothing to download from an empty transcript, so the control only
              appears once there is a conversation to take away. */}
          {messages.length > 0 && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  className="mt-2 w-full justify-start gap-2 font-medium text-muted-foreground hover:text-foreground"
                >
                  <Download className="h-4 w-4" />
                  {t("exportConversation")}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-56">
                <DropdownMenuItem onClick={() => exportConversation("md")}>
                  {t("exportMarkdown")}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => exportConversation("json")}>
                  {t("exportJson")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}

          <div className="mt-6 px-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            {t("recent")}
          </div>
          <nav className="mt-2 space-y-0.5">
            {conversations.length === 0 && (
              <div className="px-2 py-2 text-xs text-muted-foreground/70">
                {t("noConversations")}
              </div>
            )}
            {conversations.map((c) => (
              <div
                key={c.id}
                className={cn(
                  "group flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm transition hover:bg-accent",
                  c.id === conversationId
                    ? "bg-accent text-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                <button
                  onClick={() => openConversation(c)}
                  className="flex min-w-0 flex-1 items-center gap-2 text-left"
                  title={c.title}
                >
                  <MessageSquare className="h-3.5 w-3.5 shrink-0 opacity-60" />
                  <span className="truncate">{c.title}</span>
                </button>
                <span className="shrink-0 text-[10px] text-muted-foreground/60 group-hover:hidden">
                  {formatWhen(c.updatedAt, t("today"), t("yesterday"))}
                </span>
                <button
                  onClick={() => deleteConversation(c.id)}
                  aria-label={t("deleteConversation")}
                  title={t("deleteConversation")}
                  className="hidden shrink-0 text-muted-foreground/60 hover:text-destructive group-hover:block"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </nav>

          <div className="absolute inset-x-3 bottom-4 rounded-lg border border-border bg-surface p-3">
            <div className="flex items-center gap-2 text-xs font-medium text-foreground">
              <ShieldCheck className="h-3.5 w-3.5 text-primary" />
              {t("groundedTitle")}
            </div>
            <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
              {t("groundedText")}
            </p>
          </div>
        </aside>

        {/* Main */}
        <main className="flex min-h-[calc(100dvh-3.5rem)] flex-1 flex-col">
          <div className="flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-3xl px-6 py-10">
              {/* Above the transcript rather than beside the prompt: on a cold start
                  this is the answer to "why is nothing happening", and it has to be
                  where the eye already is. */}
              <BackendStatusBanner className="mb-8" />
              {messages.length === 0 && phase === "idle" ? (
                <EmptyState onPick={ask} />
              ) : (
                <div className="space-y-10">
                  {messages.map((m, idx) => {
                    const bubble =
                      m.role === "user" ? (
                        <UserBubble text={m.text} />
                      ) : (
                        <AssistantMessage
                          answer={m.answer}
                          onRegenerate={regenerateHandler(idx)}
                          busy={phase === "thinking"}
                        />
                      );
                    return (
                      <Fragment key={m.id}>
                        {idx === boundaryIdx && <MemoryBoundary />}
                        {bubble}
                      </Fragment>
                    );
                  })}
                  {phase === "thinking" && <Thinking />}
                </div>
              )}
            </div>
          </div>

          <div className="sticky bottom-0 border-t border-border bg-background/85 backdrop-blur">
            <div className="mx-auto w-full max-w-3xl px-6 py-4">
              <PromptBox
                size="compact"
                onSubmit={ask}
                placeholder={t("replyPlaceholder")}
                autoFocus
              />
              <p className="mt-2 text-center text-[11px] text-muted-foreground">
                {t("disclaimer")}
              </p>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}

function EmptyState({ onPick }: { onPick: (q: string) => void }) {
  const t = useTranslations("chat");
  const starters = [t("starter1"), t("starter2"), t("starter3"), t("starter4")];
  return (
    <div className="pt-8 text-center">
      <div className="mx-auto inline-flex h-10 w-10 items-center justify-center rounded-xl bg-accent text-primary">
        <Sparkles className="h-5 w-5" />
      </div>
      <h1 className="mt-6 text-3xl font-semibold tracking-tight text-foreground">
        {t("emptyTitle")}
      </h1>
      <p className="mx-auto mt-3 max-w-md text-sm text-muted-foreground">{t("emptyText")}</p>
      {/* Before the first question, not after it: the disclosure has to be there no
          later than the first interaction with the model (#87). The "not tax advice"
          line at the bottom of the thread is a different statement and stays. */}
      <p className="mx-auto mt-4 max-w-md text-xs text-muted-foreground">{t("aiDisclosure")}</p>
      <div className="mx-auto mt-8 grid max-w-2xl gap-2 sm:grid-cols-2">
        {starters.map((s) => (
          <button
            key={s}
            onClick={() => onPick(s)}
            className="rounded-xl border border-border bg-surface px-4 py-3 text-left text-sm text-foreground transition hover:border-border-strong hover:shadow-elevated"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

function MemoryBoundary() {
  const t = useTranslations("chat");
  return (
    <div className="flex items-center gap-3">
      <div className="h-px flex-1 bg-border" />
      <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <History className="h-3 w-3" />
        {t("memoryBoundary")}
      </span>
      <div className="h-px flex-1 bg-border" />
    </div>
  );
}

function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] rounded-2xl rounded-tr-md bg-primary px-4 py-2.5 text-[15px] leading-relaxed text-primary-foreground shadow-elevated">
        {text}
      </div>
    </div>
  );
}

function Thinking() {
  const t = useTranslations("chat");
  return (
    <div className="flex items-center gap-3 text-sm">
      <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent">
        <BrainCircuit className="h-4 w-4 text-primary" />
      </div>
      <span className="shimmer-text font-medium">{t("thinking")}</span>
    </div>
  );
}

function AssistantMessage({
  answer,
  onRegenerate,
  busy = false,
}: {
  answer: Answer;
  onRegenerate?: () => void;
  busy?: boolean;
}) {
  const t = useTranslations("chat");
  const showTrace = useShowTrace();
  const [copied, setCopied] = useState(false);
  const [feedback, setFeedback] = useState<"up" | "down" | null>(null);
  const [feedbackFailed, setFeedbackFailed] = useState(false);

  // Ratings are keyed by request_id so the backend can join them with that
  // request's log line (retrieval strategies, tools, tokens). Clicking the same
  // thumb again clears the local selection; nothing is un-sent.
  async function rate(next: "up" | "down") {
    const value = feedback === next ? null : next;
    setFeedback(value);
    setFeedbackFailed(false);
    if (!value || !answer.request_id) return;
    try {
      const res = await fetch(`${API_URL}/api/v1/tax/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: answer.request_id, rating: value }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    } catch {
      // feedback is best-effort: say so, but never block reading the answer
      setFeedbackFailed(true);
    }
  }

  async function copyAnswer() {
    // copy the plain answer without citation tags
    const text = answer.summary.replace(/\s*\[[a-z0-9][a-z0-9-]+\]/g, "");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable (e.g. http origin) — ignore */
    }
  }

  return (
    <article className="space-y-5">
      <header className="flex items-center gap-2 text-xs text-muted-foreground">
        <div className="flex h-6 w-6 items-center justify-center rounded-md bg-primary text-primary-foreground">
          <Sparkles className="h-3 w-3" />
        </div>
        <span className="font-medium text-foreground">{t("assistantName")}</span>
        {/* On every answer, not only the first one: a thread scrolls, and a name in
            the same place as a human correspondent's is exactly what #87 means by an
            AI interface that is not visibly identified as one. */}
        <span className="rounded border border-border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide">
          {t("aiBadge")}
        </span>
      </header>

      {/* Clarification: the assistant is asking the user for missing details */}
      {answer.intent === "clarification_required" && <ClarificationBanner />}

      {/* Summary card */}
      <section className="rounded-2xl border border-border bg-surface p-5 shadow-elevated">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-primary">
          {t("summary")}
        </div>
        <div className="mt-2 text-[16px] leading-relaxed text-foreground">
          <MarkdownAnswer text={answer.summary} sources={answer.sources} />
        </div>
      </section>

      {/* Structured tool results: calculation / validation / checklist cards */}
      {answer.tool_results?.map((tr, i) => (
        <ToolResultCard key={i} tool={tr.tool} data={tr.data} />
      ))}

      {/* Warnings */}
      {answer.warnings && answer.warnings.length > 0 && (
        <section className="rounded-xl border border-border bg-surface-2/50 px-4 py-3">
          <ul className="space-y-1 text-xs text-muted-foreground">
            {answer.warnings.map((w: string, i: number) => (
              <li key={i} className="flex items-start gap-2">
                <ShieldCheck className="mt-0.5 h-3 w-3 shrink-0 text-primary" />
                <span>{w}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Explanation */}
      {answer.explanation.length > 0 && (
        <section className="space-y-3">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            {t("explanation")}
          </div>
          <div className="space-y-3 text-[15px] leading-[1.75] text-foreground/90">
            {answer.explanation.map((p: string, i: number) => (
              <p key={i} className="text-pretty">
                {p}
              </p>
            ))}
          </div>
        </section>
      )}

      {/* Sources */}
      {answer.sources.length > 0 && (
        <section>
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            {t("sources")}
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {answer.sources.map((s: Source, i: number) => {
              const inner = (
                <>
                  <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-accent text-[11px] font-semibold text-primary">
                    {i + 1}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px] font-medium text-foreground">
                      {s.title}
                    </div>
                    <div className="truncate text-[11px] text-muted-foreground">
                      {s.ref || (s as { source_id?: string }).source_id}
                    </div>
                  </div>
                </>
              );
              const cls =
                "group flex items-start gap-3 rounded-xl border border-border bg-surface p-3 transition hover:border-border-strong hover:shadow-elevated";
              return s.url ? (
                <a key={i} href={s.url} target="_blank" rel="noreferrer" className={cls}>
                  {inner}
                  <ExternalLink className="mt-1 h-3.5 w-3.5 text-muted-foreground opacity-0 transition group-hover:opacity-100" />
                </a>
              ) : (
                <div key={i} className={cls}>
                  {inner}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* Related */}
      {answer.related && answer.related.length > 0 && (
        <section>
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            {t("related")}
          </div>
          <div className="flex flex-wrap gap-2">
            {answer.related.map((r: string) => (
              <button
                key={r}
                className="rounded-full border border-border bg-surface px-3 py-1.5 text-xs text-muted-foreground transition hover:border-border-strong hover:text-foreground"
              >
                {r}
              </button>
            ))}
          </div>
        </section>
      )}

      {/* Trace, unless the reader has asked not to see the working */}
      {showTrace && answer.trace && answer.trace.length > 0 && <RagTrace steps={answer.trace} />}

      {/* Token usage and estimated cost */}
      <ResponseDetails usage={answer.usage} requestId={answer.request_id} />

      {/* Actions */}
      <div className="flex items-center gap-1 pt-1 text-muted-foreground">
        <IconButton
          label={copied ? t("copied") : t("copy")}
          icon={copied ? CheckCircle2 : Copy}
          onClick={copyAnswer}
          active={copied}
        />
        {onRegenerate && (
          <IconButton
            label={t("regenerate")}
            icon={RefreshCw}
            onClick={onRegenerate}
            disabled={busy}
          />
        )}
        <IconButton
          label={t("goodAnswer")}
          icon={ThumbsUp}
          onClick={() => rate("up")}
          active={feedback === "up"}
        />
        <IconButton
          label={t("badAnswer")}
          icon={ThumbsDown}
          onClick={() => rate("down")}
          active={feedback === "down"}
        />
        {feedback && !feedbackFailed && (
          <span className="ml-1 text-[11px] text-muted-foreground">{t("feedbackThanks")}</span>
        )}
        {feedbackFailed && (
          <span className="ml-1 text-[11px] text-destructive">{t("feedbackFailed")}</span>
        )}
      </div>
    </article>
  );
}

function formatCost(cost: number): string {
  // A question costs well under a cent, so two decimals would render every
  // answer as $0.00; only a genuinely expensive one gets the shorter form.
  return `$${cost.toFixed(cost >= 0.01 ? 2 : 5)}`;
}

function count(value?: number): string {
  return typeof value === "number" ? value.toLocaleString() : "—";
}

function ResponseDetails({ usage, requestId }: { usage?: TaxAnswer["usage"]; requestId?: string }) {
  const t = useTranslations("chat");
  const [open, setOpen] = useState(false);
  // absent for locally-generated error answers — there was no request to report on
  if (!usage) return null;

  // The type says every count is present, but a conversation restored from
  // localStorage may have been written by an earlier build that had no
  // llm_calls/model/cost_usd — so a missing number shows as a dash, not "undefined".
  const rows: [string, string][] = [
    [t("detailsTokensIn"), count(usage.prompt_tokens)],
    [t("detailsTokensOut"), count(usage.completion_tokens)],
    [t("detailsTokensTotal"), count(usage.total_tokens)],
    [t("detailsCalls"), count(usage.llm_calls)],
    [
      t("detailsCost"),
      usage.cost_usd == null ? t("detailsCostUnknown") : formatCost(usage.cost_usd),
    ],
  ];
  if (usage.model) rows.push([t("detailsModel"), usage.model]);
  if (requestId) rows.push([t("detailsRequestId"), requestId]);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div className="rounded-2xl border border-border bg-surface-2/50">
        <CollapsibleTrigger asChild>
          <button className="flex w-full items-center justify-between px-4 py-3 text-left">
            <div className="flex items-center gap-2 text-[13px] font-medium text-foreground">
              <Coins className="h-3.5 w-3.5 text-primary" />
              {t("detailsTitle")}
              <span className="text-muted-foreground">
                · {count(usage.total_tokens)} {t("detailsTokensTotal").toLowerCase()}
                {usage.cost_usd != null && ` · ${formatCost(usage.cost_usd)}`}
              </span>
            </div>
            <ChevronDown
              className={cn(
                "h-4 w-4 text-muted-foreground transition-transform",
                open && "rotate-180",
              )}
            />
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="border-t border-border px-5 py-4">
            <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
              {rows.map(([label, value]) => (
                <div key={label} className="flex items-baseline justify-between gap-3">
                  <dt className="text-xs text-muted-foreground">{label}</dt>
                  <dd className="truncate font-mono text-xs text-foreground" title={value}>
                    {value}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">
              {t("detailsNote")}
            </p>
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}

// Hoisted out of MarkdownAnswer: an object literal defined inside the component is a
// new identity on every render, and these are element *types* — React unmounts and
// remounts every paragraph, list and table of every answer whenever the page
// re-renders (which it does on each auto-save). Nothing here depends on props.
const MARKDOWN_COMPONENTS: Components = {
  p: ({ children }) => <p className="mb-3 text-pretty leading-relaxed last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="mb-3 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>,
  ol: ({ children }) => <ol className="mb-3 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  h1: ({ children }) => (
    <h3 className="mb-2 mt-4 text-[15px] font-semibold first:mt-0">{children}</h3>
  ),
  h2: ({ children }) => (
    <h3 className="mb-2 mt-4 text-[15px] font-semibold first:mt-0">{children}</h3>
  ),
  h3: ({ children }) => (
    <h4 className="mb-2 mt-3 text-[14px] font-semibold first:mt-0">{children}</h4>
  ),
  strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
  a: ({ children, href }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="text-primary underline underline-offset-2"
    >
      {children}
    </a>
  ),
  code: ({ children }) => (
    <code className="rounded bg-surface-2 px-1 py-0.5 font-mono text-[13px]">{children}</code>
  ),
  table: ({ children }) => (
    <div className="mb-3 overflow-x-auto">
      <table className="w-full border-collapse text-[14px]">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border border-border bg-surface-2 px-2 py-1 text-left font-medium">
      {children}
    </th>
  ),
  td: ({ children }) => <td className="border border-border px-2 py-1">{children}</td>,
};

function MarkdownAnswer({ text, sources }: { text: string; sources: Source[] }) {
  // replace backend citation tags [source_id] with numbered refs matching
  // the numbered source cards below; drop tags for unknown sources
  const prepared = useMemo(() => {
    const index = new Map(sources.map((s, i) => [(s as { source_id?: string }).source_id, i + 1]));
    return text.replace(/\[([a-z0-9][a-z0-9-]+)\]/g, (match, sid) => {
      const n = index.get(sid);
      return n ? ` **[${n}]**` : "";
    });
  }, [text, sources]);

  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
      {prepared}
    </ReactMarkdown>
  );
}

function IconButton({
  icon: Icon,
  label,
  onClick,
  active = false,
  disabled = false,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  onClick?: () => void;
  active?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex h-8 w-8 items-center justify-center rounded-md transition hover:bg-accent hover:text-foreground",
        active && "bg-accent text-primary",
        disabled && "cursor-not-allowed opacity-40 hover:bg-transparent",
      )}
    >
      <Icon className="h-3.5 w-3.5" />
    </button>
  );
}

function RagTrace({ steps }: { steps: TraceStep[] }) {
  const t = useTranslations("chat");
  const tTrace = useTranslations("trace");
  const KNOWN = ["Query analysis", "Query rewritten (DE)", "Retrieval", "Generation", "Citations"];
  const [open, setOpen] = useState(false);
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div className="rounded-2xl border border-border bg-surface-2/50">
        <CollapsibleTrigger asChild>
          <button className="flex w-full items-center justify-between px-4 py-3 text-left">
            <div className="flex items-center gap-2 text-[13px] font-medium text-foreground">
              <BrainCircuit className="h-3.5 w-3.5 text-primary" />
              {t("traceTitle")}
              <span className="text-muted-foreground">
                · {steps.length} {t("traceSteps")}
              </span>
            </div>
            <ChevronDown
              className={cn(
                "h-4 w-4 text-muted-foreground transition-transform",
                open && "rotate-180",
              )}
            />
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <ol className="relative border-t border-border px-5 py-5">
            <div className="absolute left-[30px] top-8 bottom-8 w-px bg-border" />
            {steps.map((s, i) => (
              <li key={i} className="relative flex gap-4 py-2">
                <div className="relative z-10 flex h-6 w-6 items-center justify-center rounded-md border border-border bg-surface text-primary">
                  <s.icon className="h-3 w-3" />
                </div>
                <div className="flex-1">
                  <div className="text-[13px] font-medium text-foreground">
                    {KNOWN.includes(s.label) ? tTrace(s.label) : s.label}
                  </div>
                  <div className="text-xs text-muted-foreground">{s.detail}</div>
                </div>
              </li>
            ))}
          </ol>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}
