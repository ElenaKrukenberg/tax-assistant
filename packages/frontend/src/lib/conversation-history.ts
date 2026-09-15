/**
 * The chat page's data logic: what a message is, what gets replayed to the API,
 * and how a conversation is stored in and read back from localStorage.
 *
 * It lives here rather than in app/chat/page.tsx so it can be tested without
 * rendering anything. None of it touches React — the one concession to the UI is
 * that a trace step carries the icon component it is drawn with, because that is
 * the shape the page consumes and the reason the stored form has to strip it
 * (a component is not JSON).
 */

import {
  BrainCircuit,
  CheckCircle2,
  FileText,
  Languages,
  Search,
  Sparkles,
  Wrench,
} from "lucide-react";
import type { TaxAnswer } from "@tax-assistant/shared/types";

export type TraceStep = {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  detail: string;
};

/** TaxAnswer with the backend trace replaced by icon-enriched steps for the UI. */
export type Answer = Omit<TaxAnswer, "trace"> & {
  related?: string[];
  trace?: TraceStep[];
};

export type Message =
  | { id: string; role: "user"; text: string }
  | { id: string; role: "assistant"; answer: Answer; streaming?: boolean };

// map backend trace labels to icons for the "how this was generated" panel
export const TRACE_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  "Query analysis": Languages,
  "Query rewritten (DE)": Search,
  Retrieval: FileText,
  Generation: BrainCircuit,
  Citations: CheckCircle2,
};

function withIcon(step: StoredTraceStep): TraceStep {
  return {
    icon: step.label.startsWith("Tool:") ? Wrench : (TRACE_ICONS[step.label] ?? Sparkles),
    label: step.label,
    detail: step.detail,
  };
}

export function toAnswer(data: TaxAnswer): Answer {
  // backend trace steps are {label, detail}; attach icons for the UI
  const backendTrace = (data.trace ?? []) as StoredTraceStep[];
  return { ...data, trace: backendTrace.map(withIcon) };
}

export function errorAnswer(detail: string, summary: string): Answer {
  return {
    summary,
    explanation: [],
    sources: [],
    intent: "error",
    warnings: [`Details: ${detail}`],
    trace: [],
    // the request never reached the backend, so there is nothing to rate or trace
    request_id: "",
  };
}

// --- conversation history (localStorage) ---

export type StoredTraceStep = { label: string; detail: string };
export type StoredMessage =
  | { id: string; role: "user"; text: string }
  | {
      id: string;
      role: "assistant";
      answer: Omit<Answer, "trace"> & { trace?: StoredTraceStep[] };
    };
export type Conversation = {
  id: string;
  title: string;
  updatedAt: number;
  messages: StoredMessage[];
};

export const STORAGE_KEY = "tax-chat-conversations";
export const MAX_CONVERSATIONS = 20;

export function loadConversations(): Conversation[] {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]") as Conversation[];
  } catch {
    return [];
  }
}

export function persistConversations(list: Conversation[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(list.slice(0, MAX_CONVERSATIONS)));
  } catch {
    /* storage full/unavailable — history is best-effort */
  }
}

/**
 * Forget every stored conversation. Called when "save conversation history" is
 * switched off: a switch that only stops new writes would leave the transcripts
 * already on disk, which is not what someone turning it off is asking for.
 */
export function clearConversations(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* nothing stored is nothing to clear */
  }
}

// icon components are not serializable: strip them on save, re-attach on load
export function serializeMessages(messages: Message[]): StoredMessage[] {
  return messages.map((m) =>
    m.role === "user"
      ? m
      : {
          id: m.id,
          role: "assistant" as const,
          answer: {
            ...m.answer,
            trace: m.answer.trace?.map(({ label, detail }) => ({ label, detail })),
          },
        },
  );
}

export function deserializeMessages(stored: StoredMessage[]): Message[] {
  return stored.map((m) =>
    m.role === "user"
      ? m
      : {
          ...m,
          answer: { ...m.answer, trace: (m.answer.trace ?? []).map(withIcon) },
        },
  );
}

// One definition, so the sidebar entry and the exported file agree on the name.
export function conversationTitle(messages: Message[]): string {
  const first = messages.find((m) => m.role === "user");
  return first && first.role === "user" ? first.text.slice(0, 60) : "Conversation";
}

export function formatWhen(ts: number, todayLabel: string, yesterdayLabel: string): string {
  const d = new Date(ts);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) return todayLabel;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) return yesterdayLabel;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

// --- what travels back to the API ---

// Mirrors MAX_HISTORY_TURNS in api/schemas/tax.py — the backend rejects more,
// so trim here rather than sending a request that 422s. Keep the two in step.
export const MAX_HISTORY_TURNS = 16;

export type HistoryTurn = { role: "user" | "assistant"; text: string };

// A failed request left an error card in the transcript. Replaying "something went
// wrong" as if the assistant had said it teaches the model to apologise for a network
// fault; the question that failed stays, which is what carries the meaning.
export function isReplayable(m: Message): boolean {
  return m.role === "user"
    ? m.text.trim().length > 0
    : m.answer.intent !== "error" && m.answer.summary.trim().length > 0;
}

export function buildHistory(messages: Message[], end?: number): HistoryTurn[] {
  return messages
    .slice(0, end ?? messages.length)
    .filter(isReplayable)
    .map((m): HistoryTurn => ({
      role: m.role,
      text: m.role === "user" ? m.text : m.answer.summary,
    }))
    .slice(-MAX_HISTORY_TURNS);
}

// Index of the earliest message the next request will still replay, or null when the
// whole transcript fits. Rendered as a divider, so the point where the assistant stops
// remembering is visible instead of being discovered the hard way.
export function memoryBoundary(messages: Message[]): number | null {
  const replayable = messages.map((m, i) => (isReplayable(m) ? i : -1)).filter((i) => i >= 0);
  if (replayable.length <= MAX_HISTORY_TURNS) return null;
  return replayable[replayable.length - MAX_HISTORY_TURNS];
}
