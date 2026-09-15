# Deploying the workspace to production

The complete checklist, so nothing lives in chat history. The chat tab is
already deployed and needs none of this. "Dashboard" steps are manual; "code"
arrives with a push to `main`.

## 1. Supabase: the production project (dashboard)

Two projects on purpose (ADR 0003): dev for development and integration tests,
prod for real users only. The free tier allows exactly two.

- [ ] **New project**: `tax-assistant-prod`, region **Frankfurt (eu-central-1)**
      (near Render). Database password **without special characters**
      (`@ : / # ?` break the connection string unless URL-encoded) — and save it.
- [ ] **SQL Editor** → run in order:
      `packages/backend/db/schema/0001_tax_case.sql`, then
      `packages/backend/db/schema/0002_usage.sql`.
      Check: Table Editor shows 7 tables, all "RLS enabled".
- [ ] **Authentication → URL Configuration** (if hidden: Cmd+K, type
      "URL Configuration"):
      - Site URL: `https://tax-assistant-app.vercel.app`
      - Redirect URLs: `https://tax-assistant-app.vercel.app/**`
- [ ] Copy four values:
      - `DATABASE_URL` — Connect → **Session pooler** (host
        `...pooler.supabase.com`, port **5432**), password filled in;
      - `SUPABASE_URL` — Project Settings → API (`https://<ref>.supabase.co`,
        **not** the pooler host — no auth service lives there);
      - `SUPABASE_ANON_KEY` — same page;
      - `SUPABASE_JWKS_URL` — `https://<ref>.supabase.co/auth/v1/.well-known/jwks.json`.
- [ ] `TEST_USER_ID` is **not** needed in prod — integration tests target dev only.

## 2. Render (dashboard)

- [ ] Environment: the four values from step 1.
- [ ] `RATE_LIMIT_PER_IP=60` — the default 10/min cuts an interview off mid-way.
- [ ] `DEBUG=true` for the review period: enables the Agent-graph panel for every
      signed-in user (each sees only their own case). **Back to `false` after.**
- [ ] `LANGSMITH_API_KEY` — from smith.langchain.com (Settings → API Keys) if
      traces are wanted in prod; empty = tracing off. Sensitive values are
      redacted before upload (core/tracing.py).
- [ ] Leave `OPENROUTER_API_KEY` and `CORS_EXTRA_ORIGINS` alone — set since the
      chat deploy. `REVIEWER_MODEL` comes from render.yaml.

## 3. Vercel (dashboard)

- [ ] Environment: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`
      (values from step 1; the anon key is public by design).
- [ ] **Redeploy** — `NEXT_PUBLIC_*` are inlined at build time.

## 4. Push and smoke test

- [ ] Push `main` to both remotes (origin and personal — Vercel builds from
      personal). Wait for both builds (Render re-embeds KB/ — minutes).
- [ ] Smoke test on prod, in order:
      1. `/login` — no demo banner, email copy under the form;
      2. sign in with your own email (built-in mailer limit: **2 emails/hour for
         the whole project** — do not waste them);
      3. create the 2025 case, answer 2–3 questions — the Agent-graph panel on
         the right (DEBUG on), answers visible in the prod Table Editor;
      4. refresh the page — same question, nothing consumed;
      5. delete the case.

## Known limitations of this deploy

- **Vercel preview deploys** get the same env vars but their domains are not in
  the Redirect URLs — sign-in fails there. Prod domain works; add a preview
  mask to Redirect URLs if ever needed.
- **Emails**: until a custom SMTP, the sender is "Supabase Auth", the subject is
  default, 2 emails/hour per project. Fixed in the polish phase: SMTP + the
  templates in [supabase-email-templates.md](supabase-email-templates.md);
  Google OAuth removes the email dependency entirely.
- **First request after idle** waits ~50 s (Render free tier) — the banner
  already says so.
- LangGraph checkpoint tables are created automatically on the first request
  (`ensure_checkpoint_tables`) — no manual step.

## After the review

- [ ] `DEBUG=false` on Render.
- [ ] Revisit the limits (`INTERVIEW_CALLS_GLOBAL_PER_MONTH=3000` ≈ $10/month on
      haiku) — keep or tighten.
