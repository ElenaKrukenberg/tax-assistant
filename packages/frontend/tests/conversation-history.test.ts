/**
 * The data logic behind the chat page: what is replayed to a stateless API, where the
 * page stops remembering, and what survives a round trip through localStorage.
 */

import { describe, expect, it, vi } from "vitest";
import { FileText, Sparkles, Wrench } from "lucide-react";

import {
  MAX_HISTORY_TURNS,
  STORAGE_KEY,
  buildHistory,
  conversationTitle,
  deserializeMessages,
  errorAnswer,
  formatWhen,
  isReplayable,
  loadConversations,
  memoryBoundary,
  persistConversations,
  serializeMessages,
  toAnswer,
  type Answer,
  type Conversation,
  type Message,
} from "@/lib/conversation-history";

function user(text: string, id = text): Message {
  return { id, role: "user", text };
}

function answerOf(summary: string): Answer {
  return {
    summary,
    explanation: [],
    sources: [],
    intent: "knowledge",
    warnings: [],
    request_id: "req-1",
  } as Answer;
}

function assistant(summary: string, id = summary): Message {
  return { id, role: "assistant", answer: answerOf(summary) };
}

// --- what travels back to the API ------------------------------------------

describe("buildHistory", () => {
  it("replays both roles, oldest first, using the answer summary", () => {
    const history = buildHistory([user("74 km?"), assistant("0.30 EUR/km."), user("And 2025?")]);
    expect(history).toEqual([
      { role: "user", text: "74 km?" },
      { role: "assistant", text: "0.30 EUR/km." },
      { role: "user", text: "And 2025?" },
    ]);
  });

  it("drops error cards but keeps the question that failed", () => {
    const failed: Message = {
      id: "e",
      role: "assistant",
      answer: errorAnswer("HTTP 500", "Something went wrong"),
    };
    expect(buildHistory([user("Homeoffice?"), failed])).toEqual([
      { role: "user", text: "Homeoffice?" },
    ]);
  });

  it("drops an assistant turn with nothing in it", () => {
    expect(buildHistory([user("Q"), assistant("   ")])).toEqual([{ role: "user", text: "Q" }]);
  });

  it("keeps the newest turns when the transcript is over the cap", () => {
    // 40 turns: the request must carry the last 16, because that is what the
    // backend accepts (MAX_HISTORY_TURNS in api/schemas/tax.py).
    const messages = Array.from({ length: 40 }, (_, i) => user(`q${i}`));
    const history = buildHistory(messages);
    expect(history).toHaveLength(MAX_HISTORY_TURNS);
    expect(history[0].text).toBe("q24");
    expect(history[history.length - 1].text).toBe("q39");
  });

  it("stops at `end`, which is what keeps a regenerate from citing its own answer", () => {
    const messages = [user("Q1"), assistant("A1"), user("Q2"), assistant("A2")];
    // regenerating A2 replays only up to Q2's index
    expect(buildHistory(messages, 2)).toEqual([
      { role: "user", text: "Q1" },
      { role: "assistant", text: "A1" },
    ]);
  });

  it("is empty for a transcript with nothing replayable", () => {
    expect(buildHistory([])).toEqual([]);
    expect(buildHistory([user("   ")])).toEqual([]);
  });
});

describe("isReplayable", () => {
  it("rejects a blank question and an error answer, accepts a real exchange", () => {
    expect(isReplayable(user("Pendlerpauschale?"))).toBe(true);
    expect(isReplayable(user("  "))).toBe(false);
    expect(isReplayable(assistant("0.30 EUR/km."))).toBe(true);
    expect(
      isReplayable({ id: "e", role: "assistant", answer: errorAnswer("boom", "failed") }),
    ).toBe(false);
  });
});

describe("memoryBoundary", () => {
  it("is null while the whole transcript still fits", () => {
    const messages = Array.from({ length: MAX_HISTORY_TURNS }, (_, i) => user(`q${i}`));
    expect(memoryBoundary(messages)).toBeNull();
  });

  it("marks the earliest message the next request will still replay", () => {
    const messages = Array.from({ length: MAX_HISTORY_TURNS + 3 }, (_, i) => user(`q${i}`));
    // 19 replayable turns, 16 replayed → the divider sits on index 3
    expect(memoryBoundary(messages)).toBe(3);
    expect(buildHistory(messages)[0].text).toBe("q3");
  });

  it("counts only replayable messages, so error cards do not push the divider", () => {
    const failed: Message = {
      id: "e",
      role: "assistant",
      answer: errorAnswer("HTTP 500", "failed"),
    };
    const messages = [
      failed,
      ...Array.from({ length: MAX_HISTORY_TURNS }, (_, i) => user(`q${i}`)),
    ];
    expect(memoryBoundary(messages)).toBeNull();
  });

  it("agrees with buildHistory about where the replayed window starts", () => {
    const messages = Array.from({ length: 30 }, (_, i) =>
      i % 2 === 0 ? user(`q${i}`) : assistant(`a${i}`),
    );
    const idx = memoryBoundary(messages);
    expect(idx).not.toBeNull();
    const first = messages[idx!];
    const expected = first.role === "user" ? first.text : first.answer.summary;
    expect(buildHistory(messages)[0].text).toBe(expected);
  });
});

// --- storage round trip -----------------------------------------------------

describe("serializeMessages / deserializeMessages", () => {
  it("strips trace icons on the way out and re-attaches them on the way in", () => {
    const message: Message = {
      id: "a",
      role: "assistant",
      answer: {
        ...answerOf("A"),
        trace: [{ icon: Wrench, label: "Retrieval", detail: "5 chunks" }],
      } as Answer,
    };
    const stored = serializeMessages([message]);
    // a component is not JSON: the stored shape must survive a stringify
    expect(JSON.parse(JSON.stringify(stored))).toEqual(stored);
    expect(stored[0]).toMatchObject({
      role: "assistant",
      answer: { trace: [{ label: "Retrieval", detail: "5 chunks" }] },
    });

    const [restored] = deserializeMessages(stored);
    expect(restored.role === "assistant" && restored.answer.trace?.[0].icon).toBe(FileText);
  });

  it("gives a tool step the wrench, whatever the tool is called", () => {
    const [restored] = deserializeMessages([
      {
        id: "a",
        role: "assistant",
        answer: {
          ...answerOf("A"),
          trace: [{ label: "Tool: calculate_tax_amount", detail: "ok" }],
        },
      },
    ]);
    expect(restored.role === "assistant" && restored.answer.trace?.[0].icon).toBe(Wrench);
  });

  it("passes user messages through untouched", () => {
    const messages = [user("Q1")];
    expect(deserializeMessages(serializeMessages(messages))).toEqual(messages);
  });

  it("survives a stored answer with no trace at all", () => {
    const [restored] = deserializeMessages([
      { id: "a", role: "assistant", answer: { ...answerOf("A") } },
    ]);
    expect(restored.role === "assistant" && restored.answer.trace).toEqual([]);
  });
});

describe("loadConversations / persistConversations", () => {
  const conversation = (id: string): Conversation => ({
    id,
    title: `Conversation ${id}`,
    updatedAt: 1,
    messages: [],
  });

  it("round-trips through localStorage", () => {
    persistConversations([conversation("a")]);
    expect(loadConversations()).toEqual([conversation("a")]);
  });

  it("is empty, not broken, when the stored value is not JSON", () => {
    localStorage.setItem(STORAGE_KEY, "{not json");
    expect(loadConversations()).toEqual([]);
  });

  it("is empty when nothing was ever stored", () => {
    expect(loadConversations()).toEqual([]);
  });

  it("keeps only the newest 20 conversations", () => {
    persistConversations(Array.from({ length: 25 }, (_, i) => conversation(String(i))));
    const stored = loadConversations();
    expect(stored).toHaveLength(20);
    expect(stored[0].id).toBe("0");
  });

  it("swallows a storage failure — history is best-effort, not the product", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("QuotaExceededError");
    });
    expect(() => persistConversations([conversation("a")])).not.toThrow();
    setItem.mockRestore();
  });
});

// --- naming and dates -------------------------------------------------------

describe("conversationTitle", () => {
  it("is the first question, capped at 60 characters", () => {
    const long = "x".repeat(80);
    expect(conversationTitle([user(long)])).toHaveLength(60);
  });

  it("ignores the answers and falls back when there is no question", () => {
    expect(conversationTitle([assistant("A"), user("The question")])).toBe("The question");
    expect(conversationTitle([])).toBe("Conversation");
  });
});

describe("formatWhen", () => {
  it("names today and yesterday, and dates anything older", () => {
    const now = new Date("2026-03-10T12:00:00");
    vi.useFakeTimers();
    vi.setSystemTime(now);

    expect(formatWhen(now.getTime(), "Today", "Yesterday")).toBe("Today");
    expect(formatWhen(now.getTime() - 86_400_000, "Today", "Yesterday")).toBe("Yesterday");
    expect(formatWhen(new Date("2026-03-01T12:00:00").getTime(), "Today", "Yesterday")).toBe(
      "1 Mar",
    );
  });
});

// --- answers ----------------------------------------------------------------

describe("toAnswer", () => {
  it("attaches an icon per trace step and leaves the rest of the answer alone", () => {
    const answer = toAnswer({
      summary: "S",
      explanation: ["E"],
      sources: [],
      trace: [
        { label: "Retrieval", detail: "5 chunks" },
        { label: "Tool: build_document_checklist", detail: "ok" },
        { label: "Something new", detail: "?" },
      ],
    } as never);
    expect(answer.summary).toBe("S");
    expect(answer.explanation).toEqual(["E"]);
    expect(answer.trace?.map((s) => s.label)).toEqual([
      "Retrieval",
      "Tool: build_document_checklist",
      "Something new",
    ]);
    // known label → its own icon, any tool → the wrench, and an unrecognised label
    // still renders, with the fallback rather than undefined
    expect(answer.trace?.map((s) => s.icon)).toEqual([FileText, Wrench, Sparkles]);
  });

  it("copes with a response that carries no trace", () => {
    expect(toAnswer({ summary: "S", explanation: [], sources: [] } as never).trace).toEqual([]);
  });
});

describe("errorAnswer", () => {
  it("is marked as an error and carries no request id to rate", () => {
    const answer = errorAnswer("HTTP 429", "Too many questions");
    expect(answer.intent).toBe("error");
    expect(answer.summary).toBe("Too many questions");
    expect(answer.warnings).toEqual(["Details: HTTP 429"]);
    expect(answer.request_id).toBe("");
    // and therefore never replayed as if the assistant had said it
    expect(isReplayable({ id: "e", role: "assistant", answer })).toBe(false);
  });
});
