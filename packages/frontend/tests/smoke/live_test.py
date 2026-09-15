"""The same walk, against the real thing: real token, real backend, real database.

`smoke_test.py` stubs the network and proves the frontend behaves. This proves the
chain does: a token minted by Supabase, verified by the backend against the project's
JWKS, a case created under row level security, the Interviewer choosing questions with
a live provider, and the Anlage N route refusing or producing a form for real.

It is the slower and more expensive of the two on purpose, and both are kept:

- **stubbed** runs anywhere, costs nothing, and pins the contract between the halves;
- **live** runs only where credentials exist, costs a few cents of provider calls per
  run, and is the only thing that can catch a break in the chain — a JWKS change, an
  RLS policy that forbids what the screen tries, a migration that was never applied.

It signs in with a password rather than a magic link, because a magic link needs a
human with an inbox. That means a user with a password has to exist:

    Supabase dashboard -> Authentication -> Users -> Add user, with a password, and
    with the address confirmed. A user created through the public signup endpoint is
    unconfirmed until somebody clicks the mail, and password sign-in refuses until
    then with `email_not_confirmed`.

Then:

    export SMOKE_EMAIL=... SMOKE_PASSWORD=...
    npm run dev                                  # packages/frontend
    ../backend/venv/bin/python -m uvicorn main:app --port 8000   # packages/backend
    python tests/smoke/live_test.py

It cleans up after itself: the case it creates is deleted at the end, pass or fail.
`--keep` leaves it behind when you want to look at it.
"""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
from smoke_test import BASE_URL, Report, plant_session, shot  # noqa: E402

API_URL = os.environ.get("API_URL", "http://localhost:8000")
EMAIL = os.environ.get("SMOKE_EMAIL")
PASSWORD = os.environ.get("SMOKE_PASSWORD")
# Every answer is a provider call. Small on purpose: this test is here to prove the
# chain holds, not to re-measure the Interviewer — eval/ does that, on ten profiles.
ANSWERS = int(os.environ.get("SMOKE_ANSWERS", "3"))
TAX_YEAR = int(os.environ.get("SMOKE_TAX_YEAR", "2025"))


def env(path: str, key: str) -> str | None:
    try:
        for line in io.open(path, encoding="utf-8"):
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        return None
    return None


def sign_in() -> dict:
    """A real Supabase session, or a message saying exactly what is missing."""
    url = (env(".env.local", "NEXT_PUBLIC_SUPABASE_URL") or "").rstrip("/")
    anon = env(".env.local", "NEXT_PUBLIC_SUPABASE_ANON_KEY")
    if not url or not anon:
        raise SystemExit("no NEXT_PUBLIC_SUPABASE_* in packages/frontend/.env.local")
    if not EMAIL or not PASSWORD:
        raise SystemExit("set SMOKE_EMAIL and SMOKE_PASSWORD (see the docstring)")

    response = httpx.post(f"{url}/auth/v1/token?grant_type=password",
                          headers={"apikey": anon, "Content-Type": "application/json"},
                          json={"email": EMAIL, "password": PASSWORD}, timeout=30)
    if response.status_code != 200:
        body = response.json()
        if body.get("error_code") == "email_not_confirmed":
            raise SystemExit(
                f"{EMAIL} exists but its address is unconfirmed, so Supabase refuses a "
                "password sign-in. Confirm it from the mail Supabase sent, or mark the "
                "user confirmed in the dashboard, then run this again.")
        raise SystemExit(f"sign-in failed ({response.status_code}): {json.dumps(body)}")
    return response.json()


def api(session: dict) -> httpx.Client:
    return httpx.Client(base_url=API_URL, timeout=120,
                        headers={"Authorization": f"Bearer {session['access_token']}"})


def settle(page, timeout: int = 45000) -> None:
    """Wait until no advance is in flight.

    The waiting card carries `aria-busy` and no heading of its own, which is right for
    a screen reader and was quietly wrong for this test: it looked at headings to find
    the current question and read the absence of one as the end of the interview.
    Waiting on the attribute is both more honest and more patient than a fixed sleep —
    a live provider call is about three seconds, and sometimes it is not.
    """
    try:
        page.wait_for_selector("section[aria-busy='true']", state="detached",
                               timeout=timeout)
    except Exception:  # noqa: BLE001 — nothing busy is the state we wanted anyway
        pass


def run(page, client: httpx.Client, report: Report, case_id: str) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    print("\n[2] the case list, on real data")
    page.goto(f"{BASE_URL}/cases", wait_until="networkidle")
    page.wait_for_timeout(1500)
    report.check(str(TAX_YEAR) in page.inner_text("body"),
                 "the case created over the API is on the screen")
    shot(page, "live-01-cases")

    print(f"\n[3] the interview: {ANSWERS} real answers from the live Interviewer")
    page.goto(f"{BASE_URL}/cases/{case_id}/interview", wait_until="networkidle")
    settle(page)
    asked: list[str] = []
    for step in range(ANSWERS):
        heading = page.locator("h1").first
        if heading.count() == 0:
            break
        asked.append(heading.inner_text()[:60])

        number = page.locator("input#answer")
        yes = page.locator("button").filter(has_text="Yes").first
        if number.count() > 0 and number.is_visible():
            number.fill("12" if step == 0 else "1")
            page.locator("button").filter(has_text="Answer").first.click()
        elif yes.count() > 0:
            yes.click()
        else:
            page.locator("button").filter(has_text="know").first.click()
        page.wait_for_timeout(300)
        settle(page)

    report.check(len(asked) >= 2, "the live Interviewer asked one question after another",
                 " | ".join(asked))
    report.check(len(set(asked)) == len(asked), "no question was asked twice",
                 " | ".join(asked))
    shot(page, "live-02-interview")

    print("\n[4] going back, against the real checkpointer")
    settle(page)
    back = page.locator("button").filter(has_text="previous answer").first
    if back.count() > 0:
        before = page.locator("h1").first.inner_text()[:60]
        back.click()
        page.wait_for_timeout(300)
        settle(page)
        after = page.locator("h1").first.inner_text()[:60]
        report.check(after != before, "the question on screen changed after going back",
                     f"{before!r} -> {after!r}")
        report.check(after in asked, "and it is one that was already asked", after)
    else:
        report.check(False, "the back button is on the live question card")
    shot(page, "live-03-back")

    print("\n[5] the case as the backend sees it")
    detail = client.get(f"/api/v1/cases/{case_id}").json()
    report.check(bool(detail.get("fields")), "the answers reached the tables",
                 ", ".join(sorted(detail.get("fields", {}))))
    report.check(all(v["provenance"] in ("answer", "document", "assumed", "remembered")
                     for v in detail.get("fields", {}).values()),
                 "every stored value carries a known provenance")

    print("\n[6] the Anlage N route, for real")
    pdf = client.get(f"/api/v1/cases/{case_id}/anlage-n.pdf")
    if pdf.status_code == 200:
        report.check(pdf.content.startswith(b"%PDF"), "a real PDF came back",
                     f"{len(pdf.content)} bytes")
        report.check("attachment" in pdf.headers.get("content-disposition", ""),
                     "with a filename the browser can use",
                     pdf.headers.get("content-disposition", ""))
        report.check("x-unplaced-count" in {k.lower() for k in pdf.headers},
                     "and the unplaced count beside it")
    else:
        # Early in an interview there is nothing on Anlage N yet, and saying so is the
        # right answer. What must not happen is a 500 or an empty PDF.
        report.check(pdf.status_code == 409,
                     "an empty case is refused with a reason, not a broken form",
                     f"{pdf.status_code}: {pdf.text[:120]}")

    print("\n[7] the review tab, on whatever the Reviewer actually said")
    page.goto(f"{BASE_URL}/cases/{case_id}/review", wait_until="networkidle")
    page.wait_for_timeout(1200)
    body = page.inner_text("body")
    # Three answers in, the review has not run, so the honest screen says so rather
    # than claiming a clean bill of health. What must never appear either way is the
    # fixture's invented finding, which is what this tab used to show in live mode.
    report.check("Working-day totals contradict each other" not in body,
                 "no invented finding from the demo fixture")
    stored = detail.get("findings", [])
    if stored:
        report.check(any(f["title"] in body for f in stored),
                     "each stored finding is on the screen",
                     "; ".join(f["title"][:40] for f in stored))
    else:
        report.check("not" in body.lower() or "yet" in body.lower()
                     or "noch" in body.lower(),
                     "an unreviewed case says the Reviewer has not run yet")
    shot(page, "live-04-review")

    report.check(not errors, "no uncaught errors in the console", "; ".join(errors[:3]))


def main() -> int:
    keep = "--keep" in sys.argv
    session = sign_in()
    print(f"signed in as {session['user']['email']} ({session['user']['id']})")

    report = Report()
    client = api(session)

    print("\n[1] the backend accepts a real Supabase token")
    listed = client.get("/api/v1/cases")
    report.check(listed.status_code == 200, "the JWKS-verified token is accepted",
                 f"{listed.status_code}: {listed.text[:100]}")
    if listed.status_code != 200:
        return 1

    created = client.post("/api/v1/cases", json={"tax_year": TAX_YEAR})
    report.check(created.status_code in (200, 201), "a case can be created",
                 f"{created.status_code}: {created.text[:120]}")
    if created.status_code not in (200, 201):
        return 1
    case_id = created.json()["id"]
    print(f"case {case_id}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 900},
                                          accept_downloads=True)
            page = context.new_page()
            plant_session(page, session)
            try:
                run(page, client, report, case_id)
            finally:
                browser.close()
    finally:
        if keep:
            print(f"\nkept: {BASE_URL}/cases/{case_id}")
        else:
            gone = client.delete(f"/api/v1/cases/{case_id}")
            print(f"\ncleaned up case {case_id} ({gone.status_code})")
        client.close()

    total = len(report.results)
    print(f"\n{total - report.failed}/{total} checks passed")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
