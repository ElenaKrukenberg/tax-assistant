/**
 * Export a saved conversation as a file the user keeps.
 *
 * Two formats, because they serve different readers. Markdown is for a person —
 * most often a Steuerberater being shown what the assistant said — so it keeps
 * the citation tags and lists the sources they resolve to. JSON is for a machine
 * (a bug report, a re-import, an eval case) and stays lossless: whatever was
 * stored for the conversation is what lands in the file.
 *
 * Everything here runs in the browser against localStorage data. Nothing is
 * uploaded, which is the point: the transcript carries salaries and commutes,
 * and an export is the one place the user decides where that goes.
 */

import type { TaxAnswer } from "@tax-assistant/shared/types";

// The stored (icon-free) answer shape — see serializeMessages in app/chat/page.tsx.
type ExportedAnswer = Omit<TaxAnswer, "trace"> & {
  trace?: { label: string; detail: string }[];
};

export type ExportMessage =
  | { id: string; role: "user"; text: string }
  | { id: string; role: "assistant"; answer: ExportedAnswer };

export type ExportConversation = {
  id: string;
  title: string;
  updatedAt: number;
  messages: ExportMessage[];
};

/** Wording the document needs; passed in so this module stays free of next-intl. */
export type ExportLabels = {
  appName: string;
  assistantName: string;
  you: string;
  exported: string;
  explanation: string;
  sources: string;
  warnings: string;
  disclaimer: string;
  requestId: string;
  model: string;
};

// The format version travels in the JSON envelope: an export opened a year from
// now should say which shape it is, not be guessed at.
export const EXPORT_FORMAT_VERSION = 1;

/** Local wall-clock time, unambiguous and locale-independent: 2026-07-30 11:24. */
function timestamp(ms: number): string {
  const d = new Date(ms);
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

function datePart(ms: number): string {
  return timestamp(ms).slice(0, 10);
}

/**
 * A filename from the conversation title. Unicode letters and digits survive:
 * an ASCII-only slug would empty out a Russian or Turkish question entirely.
 */
export function exportFilename(conversation: ExportConversation, extension: string): string {
  const slug = conversation.title
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40)
    .replace(/-+$/g, "");
  const stem = slug || "conversation";
  return `steuer-assist-${stem}-${datePart(conversation.updatedAt)}.${extension}`;
}

/** Tool payloads vary by tool, so render primitives as a list and nest the rest. */
function toolLines(data: Record<string, unknown>): string[] {
  const lines: string[] = [];
  for (const [key, value] of Object.entries(data ?? {})) {
    if (value === null || value === undefined) continue;
    if (typeof value === "object") {
      lines.push(`- ${key}:`);
      lines.push("", "```json", JSON.stringify(value, null, 2), "```", "");
    } else {
      lines.push(`- ${key}: ${String(value)}`);
    }
  }
  return lines;
}

function answerSection(answer: ExportedAnswer, labels: ExportLabels): string[] {
  const out: string[] = [];
  out.push(`### ${labels.assistantName}`, "");
  // Citation tags are kept on purpose: the sources listed below are what they
  // point at, and stripping them would leave claims with nothing behind them.
  out.push(answer.summary.trim(), "");

  for (const tool of answer.tool_results ?? []) {
    out.push(`**${tool.tool}**`, "");
    out.push(...toolLines(tool.data as Record<string, unknown>));
    out.push("");
  }

  if (answer.warnings?.length) {
    out.push(`**${labels.warnings}**`, "");
    out.push(...answer.warnings.map((w) => `- ${w}`), "");
  }

  if (answer.explanation?.length) {
    out.push(`**${labels.explanation}**`, "");
    for (const paragraph of answer.explanation) out.push(paragraph.trim(), "");
  }

  if (answer.sources?.length) {
    out.push(`**${labels.sources}**`, "");
    answer.sources.forEach((s, i) => {
      const ref = s.ref || s.source_id;
      const parts = [s.title, ref, s.url].filter(Boolean);
      out.push(`${i + 1}. ${parts.join(" — ")}`);
    });
    out.push("");
  }

  const meta = [
    answer.request_id ? `${labels.requestId}: ${answer.request_id}` : "",
    answer.usage?.model ? `${labels.model}: ${answer.usage.model}` : "",
  ].filter(Boolean);
  if (meta.length) out.push(`_${meta.join(" · ")}_`, "");

  return out;
}

/** The conversation as a readable document. */
export function toMarkdown(
  conversation: ExportConversation,
  labels: ExportLabels,
  now: number,
): string {
  const out: string[] = [
    `# ${conversation.title}`,
    "",
    `_${labels.exported} ${timestamp(now)} · ${labels.appName}_`,
    "",
    `> ${labels.disclaimer}`,
    "",
  ];

  for (const message of conversation.messages) {
    out.push("---", "");
    if (message.role === "user") {
      out.push(`### ${labels.you}`, "", message.text.trim(), "");
    } else {
      out.push(...answerSection(message.answer, labels));
    }
  }

  // exactly one trailing newline
  return out
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/\n*$/, "\n");
}

/** The conversation as data: the stored shape, wrapped so it identifies itself. */
export function toJson(conversation: ExportConversation, now: number): string {
  return (
    JSON.stringify(
      {
        format: "steuer-assist-conversation",
        format_version: EXPORT_FORMAT_VERSION,
        exported_at: new Date(now).toISOString(),
        conversation,
      },
      null,
      2,
    ) + "\n"
  );
}

/** Hand the file to the browser's download machinery. */
export function downloadFile(filename: string, mime: string, content: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: `${mime};charset=utf-8` }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  // Firefox only honours the click for a link that is in the document.
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revoked on the next tick: releasing it synchronously cancels the download.
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
