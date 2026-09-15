"""Browser smoke tests for the Tax Case workspace.

What these cover and what they do not. They drive the real Next.js app in a real
browser against the **live** screens — the ones behind `isLiveBackend`, which the
Vitest suite never renders because it runs in fixture mode. What they stub is the
network: a Supabase session is planted in local storage so the app believes it is
signed in, and every backend call is answered from a script. That is deliberate.
Signing in for real needs a magic link in somebody's inbox, and the backend already
has 376 tests of its own; what is untested until now is the part in between — that
the screens render a pause, that the controls send the payload the graph expects,
and that a download reaches the browser.

So: a failure here is a frontend or contract failure, never a backend one.

Run it:
    python -m playwright install chromium        # once
    python tests/smoke/smoke_test.py             # against an already-running dev server
    BASE_URL=http://localhost:3000 python tests/smoke/smoke_test.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

BASE_URL = os.environ.get("BASE_URL", "http://localhost:3000")
SUPABASE_REF = os.environ.get("SUPABASE_REF", "epyqxmxagprhiqerbgse")
SHOTS = Path(os.environ.get("SHOT_DIR", "/tmp/smoke-shots"))

CASE_ID = "11111111-2222-3333-4444-555555555555"

# --- what the stubbed backend says ----------------------------------------------------

CASE = {"id": CASE_ID, "tax_year": 2025, "status": "gathering"}

CARRIED = [{
    "key": "commute.distance_km",
    "value": 42,
    "source": "carried over from your 2024 case",
    "text": {"en": "How far is your workplace, one way?",
             "de": "Wie weit ist Ihre Arbeitsstätte, einfache Strecke?",
             "ru": "Как далеко до работы в одну сторону?"},
    "answer_type": "integer",
}]

QUESTION = {
    "type": "question",
    "question_id": "profile.employed_months",
    "field": "profile.employed_months",
    "category": None,
    "answer_type": "integer",
    "options": [],
    "minimum": 0, "maximum": 12, "required": True,
    "text": {"en": "How many months were you employed in 2025?",
             "de": "Wie viele Monate waren Sie 2025 beschäftigt?",
             "ru": "Сколько месяцев вы работали в 2025?"},
    "rationale": "Everything else depends on it.",
}

EARLIER_QUESTION = dict(QUESTION, question_id="profile.employer_count",
                        field="profile.employer_count",
                        text={"en": "How many employers did you have?",
                              "de": "Wie viele Arbeitgeber hatten Sie?",
                              "ru": "Сколько у вас было работодателей?"})

STOP = {
    "type": "confirm_stop",
    "reason": "The remaining categories cannot plausibly add the missing 978 EUR.",
    "escalated": False,
    "gaps": [],
    "carried_over": CARRIED,
}

DEBUG = {"node": "ask_user", "rounds": 3, "asked": 2, "candidates_open": 9,
         "total_eur": 252.0, "pauschbetrag_eur": 1230.0, "revision_round": 0,
         "findings": 0, "stop_declined": False, "carried_over": 1,
         "last_decision": {"kind": "ask", "from_model": True,
                           "forced_gate": False, "question_id": "profile.employed_months"}}

DETAIL = {
    **CASE,
    "fields": {
        "profile.employed_months": {"value": 12, "provenance": "answer", "confirmed": True},
        "commute.distance_km": {"value": 42, "provenance": "remembered",
                                             "confirmed": True},
    },
    "unconfirmed_values": [],
    "expenses": [{"category": "entfernungspauschale", "amount_eur": 2730.0,
                  "form_line": "anlage_n 27-50",
                  "trace": ["20 km x 0.30 EUR x 210 days = 1260.00 EUR"],
                  "document": None}],
    "total_eur": 2730.0,
    "pauschbetrag_eur": 1230.0,
    "gaps": [],
    # What the Reviewer raised. Two, so the Review screen's ordering and its
    # with/without-category branches are both exercised by one page load.
    "findings": [
        {"severity": "blocking", "title": "Commuting days exceed the months worked",
         "reasoning": "210 days claimed against 9 employed months.",
         "category": "entfernungspauschale", "resolution": "open"},
        {"severity": "suggestion", "title": "No receipt is attached to any figure",
         "reasoning": "Nothing here is wrong; a receipt makes it defensible.",
         "category": "", "resolution": "open"},
    ],
}

MINIMAL_PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
               b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
               b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
               b"trailer<</Root 1 0 R>>\n%%EOF\n")


class Backend:
    """A scripted backend. Records what the page sent, so the payload can be asserted."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []
        self.interview_replies: list[dict] = []

    def record(self, method: str, url: str, body: object) -> None:
        self.calls.append((method, url.split("?")[0].replace(BASE_URL, ""), body))

    def sent_to(self, suffix: str) -> list[object]:
        return [body for _, url, body in self.calls if url.endswith(suffix)]

    def called(self, suffix: str) -> bool:
        return any(url.endswith(suffix) for _, url, _ in self.calls)

    def next_reply(self) -> dict:
        """The next scripted pause, or another copy of the current question."""
        if self.interview_replies:
            return self.interview_replies.pop(0)
        return {"status": "gathering", "pause": QUESTION, "done": False, "debug": DEBUG}


def install_routes(page: Page, backend: Backend) -> None:
    def handle(route):
        request = route.request
        url = request.url
        body = None
        if request.post_data:
            try:
                body = json.loads(request.post_data)
            except ValueError:
                body = request.post_data
        backend.record(request.method, url, body)

        def json_reply(payload, status=200, headers=None):
            route.fulfill(status=status, content_type="application/json",
                          headers=headers or {}, body=json.dumps(payload))

        path = url.split("?")[0]
        if path.endswith("/anlage-n.pdf"):
            route.fulfill(status=200, content_type="application/pdf",
                          headers={"Content-Disposition":
                                   'attachment; filename="anlage-n-2025-draft.pdf"',
                                   "X-Unplaced-Count": "1",
                                   # The frontend and the backend are different
                                   # origins, so these two are invisible to the page
                                   # unless the backend says they may be read. It did
                                   # not, until this test found the note beside the
                                   # download quietly claiming the form was complete.
                                   "Access-Control-Expose-Headers":
                                       "Content-Disposition, X-Unplaced-Count"},
                          body=MINIMAL_PDF)
        elif path.endswith("/interview/back"):
            json_reply({"status": "gathering", "pause": EARLIER_QUESTION,
                        "done": False, "debug": DEBUG})
        elif path.endswith("/interview/stream"):
            # Real Server-Sent Events, not JSON. The client parses `data:` lines and
            # falls back to the plain endpoint on anything it cannot read — answering
            # this one with JSON would silently exercise the fallback instead of the
            # streaming path the app actually uses.
            reply = backend.next_reply()
            frames = ["data: " + json.dumps({"type": "node", "node": node})
                      for node in ("decide_next", "ask_user")]
            frames.append("data: " + json.dumps({"type": "result", **reply}))
            route.fulfill(status=200, content_type="text/event-stream",
                          body="\n\n".join(frames) + "\n\n")
        elif path.endswith("/interview"):
            json_reply(backend.next_reply())
        elif path.endswith(f"/cases/{CASE_ID}"):
            json_reply(DETAIL)
        elif path.endswith("/cases"):
            json_reply([CASE])
        else:
            json_reply({"detail": f"unstubbed: {path}"}, status=404)

    page.route("**/api/v1/**", handle)


def fake_session() -> dict:
    """A session the app accepts and no backend would."""
    return {
        "access_token": "smoke-test-token",
        "token_type": "bearer",
        "expires_in": 3600,
        "expires_at": int(time.time()) + 3600,
        "refresh_token": "smoke-test-refresh",
        "user": {"id": "00000000-0000-0000-0000-000000000001",
                 "aud": "authenticated", "role": "authenticated",
                 "email": "smoke@example.test",
                 "app_metadata": {}, "user_metadata": {},
                 "created_at": "2025-01-01T00:00:00Z"},
    }


def plant_session(page: Page, session: dict | None = None) -> None:
    """Put a session where supabase-js looks for one, so no magic link is needed.

    supabase-js reads the session out of local storage and only goes to the network
    once it has expired. A fabricated one (the default) is enough for the stubbed run;
    `live_test.py` passes a real one it got from a password sign-in, and the same two
    lines then carry a token the backend will actually accept.
    """
    session = session or fake_session()
    page.add_init_script(
        f"window.localStorage.setItem('sb-{SUPABASE_REF}-auth-token',"
        f" JSON.stringify({json.dumps(session)}));")


# --- the checks -------------------------------------------------------------------------

class Report:
    def __init__(self) -> None:
        self.results: list[tuple[bool, str, str]] = []

    def check(self, ok: bool, name: str, detail: str = "") -> None:
        self.results.append((bool(ok), name, detail))
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))

    @property
    def failed(self) -> int:
        return sum(1 for ok, _, _ in self.results if not ok)


def shot(page: Page, name: str) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)


def run(page: Page, backend: Backend, report: Report) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

    print("\n[1] the landing page")
    page.goto(BASE_URL, wait_until="networkidle")
    report.check("Anlage N" in page.content() or "Werbungskosten" in page.content(),
                 "landing page renders")
    shot(page, "01-landing")

    print("\n[2] the case list, signed in")
    page.goto(f"{BASE_URL}/cases", wait_until="networkidle")
    page.wait_for_timeout(600)
    report.check(backend.called("/api/v1/cases"), "case list asks the live backend")
    report.check("2025" in page.inner_text("body"), "the case for 2025 is listed")
    shot(page, "02-cases")

    print("\n[3] the dashboard")
    page.goto(f"{BASE_URL}/cases/{CASE_ID}", wait_until="networkidle")
    page.wait_for_timeout(600)
    text = page.inner_text("body")
    report.check("2.730" in text or "2,730" in text or "2730" in text,
                 "the running total is shown", text[:0])
    shot(page, "03-dashboard")

    print("\n[4] the interview: a question, then going back")
    page.goto(f"{BASE_URL}/cases/{CASE_ID}/interview", wait_until="networkidle")
    page.wait_for_timeout(800)
    body = page.inner_text("body")
    report.check(any(q in body for q in QUESTION["text"].values()),
                 "the pending question is rendered")
    # The agent moves between topics mid-interview, so a question that does not say
    # which topic it belongs to reads as the interview losing its place. Reported from
    # a real run: a benefit question, then job-application costs, then the benefit
    # amount — correct, and impossible to follow.
    # inner_text() returns the text as CSS renders it, and the label is uppercased.
    report.check("about you" in body.lower(), "the question card names the topic it is in")

    back_button = page.locator("button").filter(has_text="previous answer").first
    report.check(back_button.count() > 0, "the back button is on the question card")
    if back_button.count() > 0:
        back_button.click()
        page.wait_for_timeout(700)
        report.check(backend.called("/interview/back"), "back calls the rewind endpoint")
        report.check(any(q in page.inner_text("body")
                         for q in EARLIER_QUESTION["text"].values()),
                     "the earlier question comes back on screen")
    shot(page, "04-interview-back")

    print("\n[4b] the developer panel actually draws the graph")
    # The check that was missing. The panel rendered its statistics and an empty box
    # for as long as it existed: mermaid threw on the theme's oklch() colours, the
    # throw was caught and dropped, and nothing said so. An assertion on the text
    # would have passed the whole time — only the SVG proves the diagram is there.
    diagram = page.locator(".agent-graph svg")
    report.check(diagram.count() > 0, "the agent graph renders an SVG, not an empty box")
    if diagram.count() > 0:
        markup = page.locator(".agent-graph").inner_html()
        missing = [n for n in ("decide_next", "ask_user", "confirm_stop", "review",
                               "final_approval") if n not in markup]
        report.check(not missing, "every node of the real graph is in the diagram",
                     f"missing: {missing}" if missing else "")
        report.check("active" in markup, "the node the run is paused on is marked")

    print("\n[5] the stop card with a value carried over from last year")
    backend.interview_replies.append(
        {"status": "gathering", "pause": STOP, "done": False, "debug": DEBUG})
    # Answer the question on screen; the scripted next pause is the stop proposal.
    page.locator("input#answer").first.fill("12")
    answer = page.locator("button").filter(has_text="Answer").first
    answer.wait_for(state="visible")
    answer.click()
    page.wait_for_timeout(1200)

    body = page.inner_text("body")
    report.check("earlier return" in body.lower(), "the carried-over block is on the stop card")
    report.check("42" in body, "last year's figure is shown for confirmation")
    report.check(any(q in body for q in CARRIED[0]["text"].values()),
                 "the carried value is labelled with its own question")
    shot(page, "05-stop-card")

    print("\n[5b] the wait after an answer says what is happening")
    # A provider call takes about three seconds and nothing can make it shorter, so
    # the screen has to account for the time. It used to account for it only on the
    # typed-answer button; a yes/no answer changed nothing on screen at all.
    page.evaluate("""() => {
      const original = window.fetch;
      window.__restoreFetch = () => { window.fetch = original; };
      window.fetch = async (...args) => {
        const url = typeof args[0] === 'string' ? args[0] : args[0]?.url ?? '';
        if (url.includes('/interview')) await new Promise(r => setTimeout(r, 2500));
        return original(...args);
      };
    }""")
    backend.interview_replies.append(
        {"status": "gathering", "pause": STOP, "done": False, "debug": DEBUG})
    page.locator("button").filter(has_text="Keep asking").first.click()
    page.wait_for_timeout(700)
    waiting = page.locator("section[aria-busy='true']")
    report.check(waiting.count() > 0, "a waiting card replaces the pause while it loads")
    if waiting.count() > 0:
        report.check("second" in waiting.inner_text().lower(),
                     "and it says roughly how long this takes",
                     waiting.inner_text().replace("\n", " ")[:90])
        report.check(page.locator(".quill-pen").count() > 0, "with the quill drawn")
    page.wait_for_timeout(3200)
    # Put fetch back, or every later step inherits the 2.5s handicap and the
    # assertions below read a reply that has not been sent yet.
    page.evaluate("() => window.__restoreFetch && window.__restoreFetch()")

    print("\n[6] confirming the stop sends the payload the graph expects")
    changed = page.locator("button").filter(has_text="Changed").first
    report.check(changed.count() > 0, "each carried value can be marked as changed")
    changed.click()
    page.wait_for_timeout(200)
    confirm = page.locator("button").filter(has_text="corrections").first
    report.check(confirm.count() > 0,
                 "the confirm button says corrections are included once one is marked")
    confirm.click()
    page.wait_for_timeout(1000)
    sent = [b for b in backend.sent_to("/interview/stream") + backend.sent_to("/interview")
            if isinstance(b, dict) and isinstance(b.get("resume"), dict)
            and "confirm" in (b.get("resume") or {})]
    report.check(bool(sent), "the stop reply carries {confirm, reject}",
                 json.dumps(sent[-1]["resume"]) if sent else "nothing matched")
    if sent:
        report.check(sent[-1]["resume"].get("reject") == ["commute.distance_km"],
                     "the rejected key travels with it",
                     json.dumps(sent[-1]["resume"]))
    shot(page, "06-stop-sent")

    print("\n[7] the report, and the filled Anlage N")
    page.goto(f"{BASE_URL}/cases/{CASE_ID}/report", wait_until="networkidle")
    page.wait_for_timeout(700)
    report.check("Werbungskosten" in page.inner_text("body"), "the report renders")

    download_button = page.locator("button").filter(has_text="Anlage N").first
    report.check(download_button.count() > 0, "the Anlage N button is on the report")
    if download_button.count() > 0:
        with page.expect_download(timeout=15000) as caught:
            download_button.click()
        download = caught.value
        report.check(download.suggested_filename.endswith(".pdf"),
                     "a PDF is handed to the browser", download.suggested_filename)
        page.wait_for_timeout(400)
        report.check("hand" in page.inner_text("body").lower()
                     or "manual" in page.inner_text("body").lower()
                     or "left out" in page.inner_text("body").lower(),
                     "the unplaced-figures note is shown")
    shot(page, "07-report")

    print("\n[8] the review tab shows what the Reviewer said, not a fixture")
    page.goto(f"{BASE_URL}/cases/{CASE_ID}/review", wait_until="networkidle")
    page.wait_for_timeout(700)
    body = page.inner_text("body")
    report.check("Commuting days exceed the months worked" in body,
                 "the finding from the backend is on the screen")
    report.check("No receipt is attached to any figure" in body,
                 "and so is the one without a category")
    # The fixture's own findings are the failure mode this whole change was about:
    # a screen that looks convincing and describes somebody who does not exist.
    report.check("Working-day totals contradict each other" not in body,
                 "and none of the fixture's invented findings are")
    report.check("entfernungspauschale" in body.lower(),
                 "the finding names the topic it is about")
    shot(page, "08-review")

    print("\n[9] a finished interview says it is finished, not that it errored")
    # The bug this guards: a finalized case made the interview endpoint refuse, and
    # the tab rendered the database's own sentence — "the case is finalized; reopen
    # it first" — in a red box, to somebody who had only clicked a tab.
    backend.interview_replies.append({"status": "finalized", "pause": None,
                                      "done": True, "debug": None})
    page.goto(f"{BASE_URL}/cases/{CASE_ID}/interview", wait_until="networkidle")
    page.wait_for_timeout(900)
    body = page.inner_text("body")
    report.check("interview is complete" in body.lower(),
                 "the completion card is on the screen")
    report.check("demo" not in body.lower(),
                 "and it does not call a real interview a demo")
    report.check("reopen" not in body.lower(),
                 "no database sentence reaches the user")
    # Next.js keeps its own empty role=alert on every page (the route announcer for
    # screen readers), so what matters is an alert with something in it.
    spoken = [e.inner_text().strip() for e in page.locator("[role='alert']").all()]
    report.check(not [t for t in spoken if t],
                 "and nothing is presented as an error", "; ".join(t for t in spoken if t))
    shot(page, "09-interview-finished")

    print("\n[10] other screens still load")
    for name, path in (("chat", "/chat"), ("settings", "/settings"),
                       ("documents", f"/cases/{CASE_ID}/documents")):
        page.goto(BASE_URL + path, wait_until="networkidle")
        page.wait_for_timeout(400)
        report.check(len(page.inner_text("body")) > 80, f"{name} renders")
        shot(page, f"10-{name}")

    hard = [e for e in errors if "favicon" not in e and "404" not in e]
    report.check(not hard, "no uncaught errors in the console",
                 "; ".join(hard[:3]) if hard else "")


def main() -> int:
    report = Report()
    backend = Backend()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900},
                                      accept_downloads=True)
        page = context.new_page()
        plant_session(page)
        install_routes(page, backend)
        try:
            run(page, backend, report)
        finally:
            browser.close()

    total = len(report.results)
    print(f"\n{total - report.failed}/{total} checks passed")
    print(f"screenshots: {SHOTS}")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
