# Browser smoke tests

Two Playwright scripts that walk the Tax Case workspace in a real browser, with
screenshots into `/tmp/smoke-shots`.

| | what is real | cost | needs |
|---|---|---|---|
| `smoke_test.py` | the app; the network is stubbed | nothing | a dev server |
| `live_test.py` | everything: token, backend, database, provider | a few cents a run | credentials, both servers |

Both are kept. The stubbed one runs anywhere and pins the contract between the two
halves; the live one is the only thing that can catch a break in the chain itself —
a JWKS change, an RLS policy that forbids what a screen tries, a migration nobody
applied.

## Why it exists

The Vitest suite renders the app in **fixture mode** — the `NEXT_PUBLIC_SUPABASE_*`
variables are absent, `isLiveBackend` is false, and the screens behind it never run.
Those screens are the product: the live interview, the stop card, the report. Until
this script there was nothing exercising them, and nothing at all checking that a
control sends the payload the backend expects.

It has already earned its place: it found that the Anlage N download could not read
its own response headers across origins, so the note beside it said the form was
complete when a figure had been left off. No unit test on either side could see that
— each half was correct on its own.

## What is real and what is not

Real: the Next.js app, a real Chromium, real routing, real components, real clicks.

Stubbed: the network. A Supabase session is planted in local storage so the app
believes it is signed in — a real sign-in needs a magic link in an inbox — and every
`/api/v1/**` call is answered from a script in the file. The stub answers
`/interview/stream` with genuine Server-Sent Events, because answering it with JSON
would quietly exercise the client's fallback path instead of the streaming one.

So a failure here is a frontend or contract failure. The backend has its own 378.

## Running it

```bash
python -m playwright install chromium      # once

npm run dev                                # in packages/frontend, another terminal
python tests/smoke/smoke_test.py
```

`BASE_URL` overrides the address (default `http://localhost:3000`) and `SUPABASE_REF`
the project ref the session key is named after — it has to match
`NEXT_PUBLIC_SUPABASE_URL`, or the planted session lands under a key nobody reads and
every screen redirects to the login page.

Exit code is non-zero if any check fails; every step leaves a full-page screenshot
behind, which is usually faster to read than the assertion that failed.

## The live one

It signs in with a password, because a magic link needs a human with an inbox. So a
user with a password has to exist, and the address has to be **confirmed** — a user
created through the public signup endpoint stays unconfirmed until somebody clicks
the mail, and password sign-in refuses until then with `email_not_confirmed`. The
quickest route is the Supabase dashboard: Authentication → Users → Add user, with a
password, auto-confirmed.

```bash
export SMOKE_EMAIL=... SMOKE_PASSWORD=...

npm run dev                                                    # this package
../backend/venv/bin/python -m uvicorn main:app --port 8000     # packages/backend
python tests/smoke/live_test.py
```

It creates a case, answers three questions with the live Interviewer, goes back one,
reads the case back over the API, asks for the Anlage N and opens the Review tab —
then deletes the case, pass or fail. `--keep` leaves it behind. `SMOKE_ANSWERS` changes how many questions
it answers; each one is a provider call, which is why the default is three.
