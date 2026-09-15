# Frontend — Next.js 15

The interface of the [German Tax Assistant](../../README.md): a chat over the backend's
`/api/v1/tax/ask`, built to show *how* an answer was produced rather than only the answer —
the retrieval trace, the sources actually cited, the tools that ran, and what the request
cost.

Stateless against the backend, which is what shapes most of this package: there is no
session on the server, so the conversation lives in the browser and every request replays
the turns it needs.

## Pages

| route | file | what it is |
|---|---|---|
| `/` | [app/page.tsx](./app/page.tsx) | landing page, example questions that jump straight into a chat |
| `/chat` | [app/chat/page.tsx](./app/chat/page.tsx) | the assistant |
| `/settings` | [app/settings/page.tsx](./app/settings/page.tsx) | UI language and answer language; reachable by URL only — it is deliberately not linked from the nav |

Two controls on `/settings` are real: the UI language, and the "answers follow the UI language"
toggle, which is persisted to `localStorage` and read by the chat on every request. The rest —
response depth, "show retrieval process", the theme radio, both privacy toggles, and the
Export / Delete all buttons — is scaffolding: local `useState` with nothing reading it. The theme
radio is the clearest case, because `src/styles.css` does define a `.dark` variant but nothing ever
puts that class on the document, so dark mode is unreachable rather than merely unsaved.

The nav ([app-nav.tsx](./src/components/gta/app-nav.tsx)) links `/` and `/chat` only.

## What the chat renders

The backend returns one JSON object per question
([contract](../backend/README.md#post-ask)); each field maps to something visible.

| response field | rendered as |
|---|---|
| `summary` | the answer, as Markdown (react-markdown + remark-gfm) |
| `sources` | source cards — title, section, snippet, `source_id` |
| `trace` | the collapsible "how this was generated" panel, one row per pipeline stage with an icon per stage |
| `tool_results` | a typed card per tool: calculation breakdown, validation findings, document checklist ([result-cards.tsx](./src/components/gta/result-cards.tsx)) |
| `warnings` | inline notices — topic filter matched nothing, answer withheld, and so on |
| `intent` | `clarification_required` raises the clarification banner |
| `usage` | tokens, provider calls and the USD estimate; `null` cost is shown as unknown, never as free |
| `request_id` | sent back with 👍/👎 so the rating lands on the right log line |

Trace icons are attached client-side by matching the backend's stage labels
(`Query analysis`, `Retrieval`, `Generation`, `Citations`, `Tool: …`). Adding a stage in the
backend without a mapping here is harmless: it falls back to a generic icon.

## Is the backend awake?

The API runs on Render's free plan, which spins the instance down after fifteen idle
minutes; the next request pays a cold start of around fifty seconds. That used to be met
with a silent "thinking" state *after* a question was sent.

So `/` and `/chat` both probe `GET /api/v1/tax/health` on load
([use-backend-health.ts](./src/hooks/use-backend-health.ts)) and render
[BackendStatusBanner](./src/components/gta/backend-status-banner.tsx):

| after | shows |
|---|---|
| under 2s | nothing — a healthy backend is not news |
| 2s | "The server is waking up — your first answer may take up to a minute." |
| 90s, or a failed request | "The server is not responding." |

Firing this on the landing page is the part that actually helps: the probe *is* what wakes
the instance, so the boot overlaps with the time spent typing the first question instead of
following it. `/health` is the right probe — no LLM call, no rate limit, and the same path
Render's own health check uses.

## Conversation state

The logic below lives in [src/lib/conversation-history.ts](./src/lib/conversation-history.ts),
apart from the page rather than inside it so it can be tested without rendering anything.

There is no backend session. `/chat` keeps up to 20 conversations in `localStorage` and
sends the recent turns with each question, oldest first, capped at 16 — the same limit
`api/schemas/tax.py` enforces, mirrored here so an over-long thread is trimmed instead of
producing a 422. The point where the assistant stops remembering is drawn as a divider in
the transcript rather than left to be discovered the hard way.

Turns that failed are not replayed: an error card saying "something went wrong" would
teach the model to apologise for a network fault. The question that failed stays, because
that is what carries the meaning.

Three further consequences worth knowing:

- Icon components are not serialisable, so they are stripped on save and re-attached on
  load. Anything read out of `localStorage` is treated as possibly written by an older
  build.
- Leaving a conversation abandons the question in flight. Starting a new thread or opening an
  older one aborts the request and drops its reply; without that the answer lands in whatever
  transcript is on screen, which showed up as a brand-new chat displaying an answer to a question
  that was no longer there.
- History is best-effort. A full or unavailable `localStorage` is swallowed — losing the
  sidebar must never block reading an answer. Feedback is best-effort in the same way: a
  failed `POST /feedback` shows a small notice and nothing else.

### Taking a conversation out of the browser

**Download conversation** in the sidebar writes the active thread to a file. Two formats, because
they serve different readers: `.md` is for a person — most often a Steuerberater being shown what the
assistant said, so it keeps the inline citation tags and lists the sources they resolve to — and
`.json` is lossless, the stored shape wrapped in an envelope that names its own format version, for a
bug report or a re-import.

Formatting lives in [src/lib/conversation-export.ts](./src/lib/conversation-export.ts), which knows
nothing about React or next-intl: the document's wording is passed in, so one implementation serves
all four languages. It exports the *stored* form rather than the rendered state, for the same reason
the stored form exists — icon components do not serialise, and the stored shape is the one a
re-import would have to read. Nothing is uploaded; the transcript carries salaries and commutes, and
the download is the one place the user decides where that goes.

## Languages

Four UI languages — English, German, Turkish, Russian — via `next-intl` with the message
catalogues in [src/i18n/messages/](./src/i18n/messages/). The locale is detected from
`navigator.language` on first load, then remembered in `localStorage`; the server and first
paint always render `en`, because `localStorage` and `navigator` are client-only.

The **answer** language is separate from the UI language. By default the chat sends
`language: "auto"` and the backend answers in whichever language the question was asked in.
The settings toggle "answers follow the UI language" switches that to `language: <locale>`.

## Development

```bash
npm run dev          # next dev — http://localhost:3000
npm run build        # production build
npm run start        # serve the build
npm run test         # vitest, once
npm run test:watch   # vitest, watching
npm run lint         # eslint
npm run format       # prettier
```

From the repository root, `npm run dev` starts this and the backend together.

## Tests

Vitest with React Testing Library in jsdom, 64 tests in [tests/](./tests/). Vitest rather
than Jest because this is an ESM package with ESM-only dependencies (`react-markdown`,
`remark-gfm`), which Jest needs transform plumbing to load at all.

| file | covers |
|---|---|
| `conversation-history.test.ts` | what is replayed to the stateless API (`buildHistory`), where the memory divider lands, the icon strip/re-attach round trip through `localStorage`, titles and relative dates |
| `conversation-export.test.ts` | both export formats: the Markdown document's sections, the Unicode-preserving filename slug, that the JSON stays lossless, and the download's blob lifecycle |
| `chat-page.test.tsx` | the page's state transitions, driven through the UI: ask, follow up (and the history that travels with it), 429, unreachable backend, regenerate, save/reopen/delete, and abandoning an answer in flight |
| `backend-health.test.tsx` | the cold-start banner: silent while healthy, warning at 2s, cleared when the instance boots, and switching to "not responding" on failure or after 90s |

`fetch` is the only thing stubbed — plus `next/navigation`, which has no router in a test
environment. The stub honours the abort signal the way a real `fetch` does, because the
"conversation switched mid-answer" behaviour *is* the interaction between that signal and
the handler's `catch`: a stub that ignored it would make the test pass for the wrong reason.

[tests/setup.ts](./tests/setup.ts) holds the jsdom shims (`ResizeObserver`, `matchMedia`,
pointer capture — Radix uses all three) and clears web storage between tests. Every shim is
there because something failed without it.

One test-driven fix worth noting: the markdown `components` map was built inside the render
function, so it was a new set of element *types* on every render and React remounted every
paragraph, list and table of every answer whenever the page re-rendered — which it does on
each auto-save. It is hoisted to module scope now. The symptom was a test finding an element
and then failing to assert on it, because the node it held had been replaced mid-assertion.

## Types

Nothing in this package hand-writes the shape of a backend response. `TaxAnswer`, `Source`
and friends are imported from `@tax-assistant/shared`, which is generated from the
backend's OpenAPI schema:

```bash
npm run generate-types    # backend must be running on :8000
```

Details in [packages/shared/README.md](../shared/README.md).

## Configuration

One variable, `NEXT_PUBLIC_API_URL`, defaulting to `http://localhost:8000`.

It is inlined into the bundle at **build** time, which has one consequence that has cost
time before: setting it on Vercel after a deploy changes nothing until the frontend is
rebuilt, and if it is missing entirely the deployed app calls `localhost` and the symptom
looks exactly like a dead backend. A browser-side `network/CORS error reaching <url>` in the
chat is the message to look for — it names the URL actually compiled in.

The backend must also allow this origin; see
[Environment variables](../../README.md#environment-variables) in the root README.

## Stack

Next.js 15 (App Router) · React 19 · TypeScript · Tailwind CSS v4 · shadcn/ui over Radix
primitives · next-intl · react-markdown + remark-gfm · lucide-react · Vitest + React
Testing Library.

Two honest notes about the dependency list. A `QueryClientProvider` is mounted in
[app/providers.tsx](./app/providers.tsx), but the chat calls the API with plain `fetch` —
React Query is wired up and not yet used. Zod, react-hook-form, recharts and sonner arrive
with the shadcn/ui scaffolding in `src/components/ui/` and are not used by app code.

`src/components/ui/` is generated shadcn/ui — regenerate through the component recipes
rather than editing by hand. Everything specific to this app lives in
`src/components/gta/`.
