/**
 * The export is the one place a transcript — salaries, commutes and all — leaves the
 * browser, at the user's choosing. So the tests care about two things: that the
 * document is complete enough to hand to a Steuerberater (citations kept, sources
 * listed), and that the JSON stays lossless.
 */

import { describe, expect, it, vi } from "vitest";

import {
  EXPORT_FORMAT_VERSION,
  downloadFile,
  exportFilename,
  toJson,
  toMarkdown,
  type ExportConversation,
  type ExportLabels,
  type ExportMessage,
} from "@/lib/conversation-export";

/**
 * Fixtures are deliberately partial. The generated TaxAnswer type makes every field
 * required and types a tool payload as an opaque record, so spelling one out in full
 * per case would bury what the case is about — and the module under test reads only
 * what it is given.
 */
const message = (m: Record<string, unknown>) => m as unknown as ExportMessage;

const LABELS: ExportLabels = {
  appName: "Steuer Assist",
  assistantName: "Steuer Assist",
  you: "You",
  exported: "Exported",
  explanation: "Explanation",
  sources: "Official Sources",
  warnings: "Warnings",
  disclaimer: "General information, not tax advice.",
  requestId: "Request ID",
  model: "Model",
};

// 2026-03-10 14:30 local time, so the assertions do not depend on the runner's zone
const NOW = new Date("2026-03-10T14:30:00").getTime();

function conversation(overrides: Partial<ExportConversation> = {}): ExportConversation {
  return {
    id: "c1",
    title: "Entfernungspauschale 2025",
    updatedAt: NOW,
    messages: [
      message({ id: "m1", role: "user", text: "How much is the commuter allowance?" }),
      message({
        id: "m2",
        role: "assistant",
        answer: {
          summary: "0.30 EUR per km up to 20 km [lsth-2025-par-9].",
          explanation: ["From km 21 it is 0.38 EUR."],
          sources: [
            {
              title: "LStH 2025 § 9",
              ref: "§ 9 EStG",
              url: "https://example.test/lsth",
              source_id: "lsth-2025-par-9",
              section: "§ 9",
              snippet: "",
            },
          ],
          intent: "knowledge",
          warnings: ["Figures apply to tax year 2025."],
          usage: {
            prompt_tokens: 10,
            completion_tokens: 5,
            total_tokens: 15,
            llm_calls: 2,
            model: "anthropic/claude-haiku-4.5",
            cost_usd: 0.0001,
          },
          tool_results: [
            {
              tool: "calculate_tax_amount",
              data: { total_eur: 1234.5, breakdown: { first_20_km: 600 } },
            },
          ],
          request_id: "abc123",
        },
      }),
    ],
    ...overrides,
  };
}

describe("exportFilename", () => {
  it("slugs the title and stamps the conversation's date", () => {
    expect(exportFilename(conversation(), "md")).toBe(
      "steuer-assist-entfernungspauschale-2025-2026-03-10.md",
    );
  });

  it("keeps non-Latin titles instead of slugging them away", () => {
    // an ASCII-only slug would empty these out entirely
    expect(exportFilename(conversation({ title: "Можно ли вычесть кабинет?" }), "json")).toContain(
      "можно-ли-вычесть-кабинет",
    );
    expect(exportFilename(conversation({ title: "Ev ofisi düşebilir miyim?" }), "md")).toContain(
      "ev-ofisi-düşebilir-miyim",
    );
  });

  it("falls back to a usable name when the title has nothing to slug", () => {
    expect(exportFilename(conversation({ title: "??? !!!" }), "md")).toBe(
      "steuer-assist-conversation-2026-03-10.md",
    );
  });

  it("never ends the stem on a dash, even when the cut lands on one", () => {
    const title = `${"a".repeat(39)} tail`; // character 40 is the separator
    const stem = exportFilename(conversation({ title }), "md");
    expect(stem).not.toContain("--2026");
    expect(stem).toBe(`steuer-assist-${"a".repeat(39)}-2026-03-10.md`);
  });
});

describe("toMarkdown", () => {
  const document = toMarkdown(conversation(), LABELS, NOW);

  it("opens with the title, the export time and the disclaimer", () => {
    expect(document.startsWith("# Entfernungspauschale 2025\n")).toBe(true);
    expect(document).toContain("_Exported 2026-03-10 14:30 · Steuer Assist_");
    expect(document).toContain("> General information, not tax advice.");
  });

  it("keeps the citation tags and lists what they point at", () => {
    // stripping the tags would leave claims with nothing behind them
    expect(document).toContain("[lsth-2025-par-9]");
    expect(document).toContain("1. LStH 2025 § 9 — § 9 EStG — https://example.test/lsth");
  });

  it("carries the question, the explanation, the warnings and the answer metadata", () => {
    expect(document).toContain("### You\n\nHow much is the commuter allowance?");
    expect(document).toContain("From km 21 it is 0.38 EUR.");
    expect(document).toContain("- Figures apply to tax year 2025.");
    expect(document).toContain("_Request ID: abc123 · Model: anthropic/claude-haiku-4.5_");
  });

  it("renders tool output: primitives as a list, nested data as JSON", () => {
    expect(document).toContain("- total_eur: 1234.5");
    expect(document).toContain("- breakdown:");
    expect(document).toContain('"first_20_km": 600');
  });

  it("omits the sections an answer does not have", () => {
    const bare = toMarkdown(
      conversation({
        messages: [
          message({
            id: "m1",
            role: "assistant",
            answer: { summary: "Short answer.", explanation: [], sources: [], request_id: "" },
          }),
        ],
      }),
      LABELS,
      NOW,
    );
    expect(bare).toContain("Short answer.");
    expect(bare).not.toContain("Official Sources");
    expect(bare).not.toContain("Explanation");
    expect(bare).not.toContain("Request ID");
  });

  it("ends on exactly one newline and never stacks blank lines", () => {
    expect(document.endsWith("\n")).toBe(true);
    expect(document.endsWith("\n\n")).toBe(false);
    expect(document).not.toMatch(/\n{3,}/);
  });

  it("falls back to the source id when a source has no human ref", () => {
    const document = toMarkdown(
      conversation({
        messages: [
          message({
            id: "m1",
            role: "assistant",
            answer: {
              summary: "S",
              explanation: [],
              sources: [
                { title: "T", ref: "", url: "", source_id: "some-id", section: "", snippet: "" },
              ],
              request_id: "",
            },
          }),
        ],
      }),
      LABELS,
      NOW,
    );
    expect(document).toContain("1. T — some-id");
  });
});

describe("toJson", () => {
  it("wraps the stored conversation so an old file can identify itself", () => {
    const parsed = JSON.parse(toJson(conversation(), NOW));
    expect(parsed.format).toBe("steuer-assist-conversation");
    expect(parsed.format_version).toBe(EXPORT_FORMAT_VERSION);
    expect(parsed.exported_at).toBe(new Date(NOW).toISOString());
  });

  it("is lossless — the stored shape comes back unchanged", () => {
    const original = conversation();
    expect(JSON.parse(toJson(original, NOW)).conversation).toEqual(original);
  });
});

describe("downloadFile", () => {
  it("hands the browser a named blob and releases it on the next tick", () => {
    const createObjectURL = vi.fn(() => "blob:url");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });
    vi.useFakeTimers();

    const clicked: HTMLAnchorElement[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      // Firefox only honours the click for a link that is in the document
      expect(this.isConnected).toBe(true);
      clicked.push(this);
    });

    downloadFile("report.md", "text/markdown", "# hi\n");

    expect(clicked).toHaveLength(1);
    expect(clicked[0].download).toBe("report.md");
    expect(clicked[0].href).toBe("blob:url");
    expect(document.querySelector("a")).toBeNull(); // removed after clicking

    // revoking synchronously would cancel the download
    expect(revokeObjectURL).not.toHaveBeenCalled();
    vi.runAllTimers();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:url");

    click.mockRestore();
    vi.unstubAllGlobals();
  });
});
