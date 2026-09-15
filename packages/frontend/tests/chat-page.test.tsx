/**
 * The chat page's state transitions, driven through the UI rather than by poking at
 * internals: ask, follow up, fail, get throttled, switch conversations mid-answer.
 *
 * `fetch` is the only thing stubbed, and the stub honours the abort signal the way a
 * real one does — the "conversation switched" behaviour is exactly the interaction
 * between that signal and the handler's catch block, so a stub that ignored it would
 * make the test pass for the wrong reason.
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import ChatPage from "../app/chat/page";
import { LocaleProvider } from "@/i18n/locale-provider";
import { STORAGE_KEY, type Conversation } from "@/lib/conversation-history";
import { KEYS } from "@/lib/preferences";

const { routerPush, routerReplace } = vi.hoisted(() => ({
  routerPush: vi.fn(),
  routerReplace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush, replace: routerReplace, prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/chat",
}));

const QUESTION = "How much is the commuter allowance?";
const SUMMARY = "It is 0.30 EUR per kilometre for the first 20 km.";

function answerPayload(summary = SUMMARY) {
  return {
    summary,
    explanation: ["From km 21 it is 0.38 EUR."],
    sources: [],
    trace: [{ label: "Retrieval", detail: "5 chunks" }],
    intent: "knowledge",
    warnings: [],
    usage: {
      prompt_tokens: 10,
      completion_tokens: 5,
      total_tokens: 15,
      llm_calls: 2,
      model: "anthropic/claude-haiku-4.5",
      cost_usd: 0.0001,
    },
    tool_results: [],
    request_id: "req-abc",
  };
}

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

// The page also probes /health on mount (the cold-start banner), so the stubs answer
// that separately: an awake backend, which renders no banner and keeps these tests
// about asking. The banner itself is covered in backend-health.test.tsx.
const isHealthCheck = (url: string) => url.includes("/health");
const healthy = () => new Response(JSON.stringify({ status: "ok" }), { status: 200 });

/** Stub fetch with one queued /ask outcome per call; falls back to the last one. */
function stubFetch(...outcomes: (Response | Error)[]) {
  const calls: { url: string; body: Record<string, unknown> }[] = [];
  let i = 0;
  const fetchMock = vi.fn(async (url: string, init: RequestInit) => {
    if (isHealthCheck(url)) return healthy();
    calls.push({ url, body: JSON.parse(String(init.body)) });
    const outcome = outcomes[Math.min(i++, outcomes.length - 1)];
    if (outcome instanceof Error) throw outcome;
    return outcome;
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, calls };
}

/** An /ask that stays in flight until settled — and rejects if it is aborted. */
function stubPendingFetch() {
  let resolveWith!: (response: Response) => void;
  const fetchMock = vi.fn(async (url: string, init: RequestInit) => {
    if (isHealthCheck(url)) return healthy();
    return new Promise<Response>((resolve, reject) => {
      resolveWith = resolve;
      init.signal?.addEventListener("abort", () =>
        reject(new DOMException("The operation was aborted.", "AbortError")),
      );
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, resolveWith: (r: Response) => resolveWith(r) };
}

function renderChat() {
  return render(
    <LocaleProvider>
      <ChatPage />
    </LocaleProvider>,
  );
}

async function ask(question: string) {
  const user = userEvent.setup();
  // pasted rather than typed: user.type re-renders the page once per keystroke, which
  // is 40 renders per question here and enough to push the suite into async timeouts
  await user.click(screen.getByPlaceholderText("Reply to the assistant…"));
  await user.paste(question);
  await user.click(screen.getByRole("button", { name: "Send" }));
  return user;
}

describe("asking a question", () => {
  it("renders the answer and clears the thinking state", async () => {
    const { calls } = stubFetch(jsonResponse(answerPayload()));
    renderChat();

    await ask(QUESTION);

    expect(await screen.findByText(SUMMARY)).toBeInTheDocument();
    // scoped to the transcript: the sidebar entry carries the same text
    expect(within(screen.getByRole("main")).getByText(QUESTION)).toBeInTheDocument();
    expect(screen.queryByText("Retrieving official sources…")).not.toBeInTheDocument();
    expect(calls[0].url).toContain("/api/v1/tax/ask");
    expect(calls[0].body).toMatchObject({ text: QUESTION, language: "auto", history: [] });
  });

  it("shows the thinking state until the answer arrives", async () => {
    const { resolveWith } = stubPendingFetch();
    renderChat();

    await ask(QUESTION);
    expect(await screen.findByText("Retrieving official sources…")).toBeInTheDocument();

    resolveWith(jsonResponse(answerPayload()));
    expect(await screen.findByText(SUMMARY)).toBeInTheDocument();
    expect(screen.queryByText("Retrieving official sources…")).not.toBeInTheDocument();
  });

  it("replays the earlier turns with a follow-up, because the API is stateless", async () => {
    const { calls } = stubFetch(
      jsonResponse(answerPayload()),
      jsonResponse(answerPayload("74 km.")),
    );
    renderChat();

    await ask(QUESTION);
    await screen.findByText(SUMMARY);
    await ask("And for 74 km?");
    await screen.findByText("74 km.");

    expect(calls[1].body.history).toEqual([
      { role: "user", text: QUESTION },
      { role: "assistant", text: SUMMARY },
    ]);
    expect(calls[1].body.text).toBe("And for 74 km?");
  });

  it("answers the question handed over from the landing page, once", async () => {
    // the landing page passes the question via sessionStorage so ?q= never flashes
    sessionStorage.setItem("pending-question", QUESTION);
    const { calls } = stubFetch(jsonResponse(answerPayload()));
    renderChat();

    expect(await screen.findByText(SUMMARY)).toBeInTheDocument();
    expect(calls[0].body.text).toBe(QUESTION);
    expect(calls).toHaveLength(1);
    // consumed, so a remount does not re-ask it
    expect(sessionStorage.getItem("pending-question")).toBeNull();
  });
});

describe("failures", () => {
  it("shows the wait on a 429 instead of the generic 'is the backend running?'", async () => {
    stubFetch(
      new Response(JSON.stringify({ detail: "Too many requests.", error_code: "RATE_LIMITED" }), {
        status: 429,
        headers: { "Retry-After": "42" },
      }),
    );
    renderChat();

    await ask(QUESTION);

    expect(
      await screen.findByText(/Too many questions in a short time.*42 seconds/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/make sure the backend is running/)).not.toBeInTheDocument();
  });

  it("falls back to 60 seconds when the 429 carries no Retry-After", async () => {
    stubFetch(new Response("{}", { status: 429 }));
    renderChat();

    await ask(QUESTION);

    expect(await screen.findByText(/about 60 seconds/)).toBeInTheDocument();
  });

  it("reports an unreachable backend and does not replay the failure as an answer", async () => {
    const { calls } = stubFetch(new TypeError("Failed to fetch"), jsonResponse(answerPayload()));
    renderChat();

    await ask(QUESTION);
    expect(await screen.findByText(/make sure the backend is running/)).toBeInTheDocument();

    // retrying sends the question again, but not the error card: the model must not
    // learn to apologise for a network fault
    await ask("Try again?");
    await screen.findByText(SUMMARY);
    expect(calls[1].body.history).toEqual([{ role: "user", text: QUESTION }]);
  });

  it("reports an unexpected status with the status in the details", async () => {
    stubFetch(new Response("boom", { status: 500 }));
    renderChat();

    await ask(QUESTION);

    expect(await screen.findByText(/make sure the backend is running/)).toBeInTheDocument();
    expect(screen.getByText(/HTTP 500/)).toBeInTheDocument();
  });
});

describe("backend status", () => {
  it("carries the status banner, so a cold start is explained before asking", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (isHealthCheck(url)) throw new TypeError("Failed to fetch");
        return jsonResponse(answerPayload());
      }),
    );
    renderChat();

    // the banner's own behaviour is covered in backend-health.test.tsx; this is only
    // that the page mounts it
    expect(await screen.findByText(/The server is not responding/)).toBeInTheDocument();
  });
});

describe("conversations", () => {
  it("abandons the answer in flight when a new conversation is started", async () => {
    const { resolveWith } = stubPendingFetch();
    renderChat();

    const user = await ask(QUESTION);
    await screen.findByText("Retrieving official sources…");

    await user.click(screen.getByRole("button", { name: "New conversation" }));
    // the reply lands after the switch: it belonged to the conversation that asked
    resolveWith(jsonResponse(answerPayload()));

    await waitFor(() =>
      expect(screen.queryByText("Retrieving official sources…")).not.toBeInTheDocument(),
    );
    expect(screen.queryByText(SUMMARY)).not.toBeInTheDocument();
    // an abandoned request is not a failure, so it must not leave an error card either
    expect(screen.queryByText(/make sure the backend is running/)).not.toBeInTheDocument();
    expect(screen.getByText("Guten Tag. What would you like to understand?")).toBeInTheDocument();
  });

  it("saves the conversation and restores it when reopened", async () => {
    stubFetch(jsonResponse(answerPayload()));
    renderChat();

    const user = await ask(QUESTION);
    await screen.findByText(SUMMARY);

    await waitFor(() => expect(localStorage.getItem(STORAGE_KEY)).toContain(QUESTION));
    const [stored] = JSON.parse(localStorage.getItem(STORAGE_KEY)!) as Conversation[];
    expect(stored.title).toBe(QUESTION);
    // trace icons are components, so only their labels may reach storage
    expect(stored.messages[1]).toMatchObject({
      answer: { trace: [{ label: "Retrieval", detail: "5 chunks" }] },
    });

    await user.click(screen.getByRole("button", { name: "New conversation" }));
    expect(screen.queryByText(SUMMARY)).not.toBeInTheDocument();

    const sidebar = screen.getByRole("complementary");
    await user.click(within(sidebar).getByTitle(QUESTION));
    expect(await screen.findByText(SUMMARY)).toBeInTheDocument();
  });

  it("lists the conversations saved by an earlier visit", async () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify([
        { id: "c1", title: "Earlier question", updatedAt: Date.now(), messages: [] },
      ] satisfies Conversation[]),
    );
    stubFetch(jsonResponse(answerPayload()));
    renderChat();

    const sidebar = screen.getByRole("complementary");
    expect(await within(sidebar).findByTitle("Earlier question")).toBeInTheDocument();
    expect(within(sidebar).getByText("Today")).toBeInTheDocument();
  });

  it("drops a deleted conversation from the list and from storage", async () => {
    stubFetch(jsonResponse(answerPayload()));
    renderChat();

    const user = await ask(QUESTION);
    await screen.findByText(SUMMARY);
    const sidebar = screen.getByRole("complementary");
    await waitFor(() => expect(within(sidebar).getByTitle(QUESTION)).toBeInTheDocument());

    await user.click(within(sidebar).getByRole("button", { name: "Delete conversation" }));

    await waitFor(() => expect(within(sidebar).queryByTitle(QUESTION)).not.toBeInTheDocument());
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!)).toEqual([]);
    // deleting the open conversation clears the transcript too
    expect(screen.queryByText(SUMMARY)).not.toBeInTheDocument();
  });
});

describe("regenerating an answer", () => {
  it("re-asks the question and replays only what came before it", async () => {
    const { calls } = stubFetch(
      jsonResponse(answerPayload()),
      jsonResponse(answerPayload("A second attempt.")),
    );
    renderChat();

    const user = await ask(QUESTION);
    await screen.findByText(SUMMARY);

    await user.click(screen.getByRole("button", { name: "Regenerate" }));
    expect(await screen.findByText("A second attempt.")).toBeInTheDocument();

    expect(calls[1].body.text).toBe(QUESTION);
    // the answer being regenerated must not be fed back as its own context
    expect(calls[1].body.history).toEqual([]);
    // and the question is not duplicated in the transcript
    expect(within(screen.getByRole("main")).getAllByText(QUESTION)).toHaveLength(1);
  });
});
/**
 * The Settings screen writes these; this page is where they have to show. A control
 * that persists a value nothing reads is the state #18 was opened to end, so each of
 * the three is checked here, at the far end, rather than at the switch.
 */
describe("preferences from the Settings screen", () => {
  it("sends the stored response depth with the question", async () => {
    localStorage.setItem(KEYS.depth, "detailed");
    const { calls } = stubFetch(jsonResponse(answerPayload()));
    renderChat();

    await ask(QUESTION);
    await screen.findByText(SUMMARY);

    expect(calls[0].body.depth).toBe("detailed");
  });

  it("asks for a balanced answer when the control was never touched", async () => {
    const { calls } = stubFetch(jsonResponse(answerPayload()));
    renderChat();

    await ask(QUESTION);
    await screen.findByText(SUMMARY);

    expect(calls[0].body.depth).toBe("balanced");
  });

  it("hides the retrieval steps when the reader asked not to see them", async () => {
    localStorage.setItem(KEYS.showTrace, "false");
    stubFetch(jsonResponse(answerPayload()));
    renderChat();

    await ask(QUESTION);
    await screen.findByText(SUMMARY);

    // the answer is unchanged - only the working is hidden
    expect(screen.queryByText("How this answer was generated")).not.toBeInTheDocument();
  });

  it("shows them by default", async () => {
    stubFetch(jsonResponse(answerPayload()));
    renderChat();

    await ask(QUESTION);
    await screen.findByText(SUMMARY);

    expect(await screen.findByText("How this answer was generated")).toBeInTheDocument();
  });

  it("writes nothing to storage when history is switched off", async () => {
    localStorage.setItem(KEYS.saveHistory, "false");
    stubFetch(jsonResponse(answerPayload()));
    renderChat();

    await ask(QUESTION);
    await screen.findByText(SUMMARY);

    // the conversation is on screen and answerable; it simply outlives nothing
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("does not read back what an earlier visit stored, either", async () => {
    localStorage.setItem(KEYS.saveHistory, "false");
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify([
        { id: "c1", title: "Earlier question", updatedAt: Date.now(), messages: [] },
      ] satisfies Conversation[]),
    );
    stubFetch(jsonResponse(answerPayload()));
    renderChat();

    const sidebar = screen.getByRole("complementary");
    await waitFor(() =>
      expect(within(sidebar).queryByTitle("Earlier question")).not.toBeInTheDocument(),
    );
  });
});
