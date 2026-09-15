"""The /ask limit exists to cap spend, so the test that matters is not "a 429 came
back" but "no provider call happened" — see test_a_refused_request_costs_nothing.
"""

import pytest
from fastapi.testclient import TestClient

from core.rate_limit import RateLimited, RateLimiter, SlidingWindow, client_key, get_limiter
from core.config import get_settings
from core.dependencies import get_llm_client, get_retriever
from main import app


@pytest.fixture
def tight_limits():
    """Shrink the live limiter for the duration of one test, then put it back."""
    limiter = get_limiter()
    original = (limiter.per_ip.limit, limiter.overall.limit)

    def apply(per_ip: int, overall: int):
        limiter.per_ip.limit = per_ip
        limiter.overall.limit = overall
        limiter.reset()
        return limiter

    yield apply
    limiter.per_ip.limit, limiter.overall.limit = original
    limiter.reset()


@pytest.fixture
def limited_client(fake_llm, fake_retriever):
    """Clients whose apparent address is controllable.

    This starlette's TestClient takes no `client=` argument, so two clients are
    told apart the way the deployment does it: one trusted proxy in front, and
    the address in X-Forwarded-For.
    """
    app.dependency_overrides[get_llm_client] = lambda: fake_llm
    app.dependency_overrides[get_retriever] = lambda: fake_retriever
    settings = get_settings()
    trusted = settings.trust_proxy_header
    settings.trust_proxy_header = True
    http = TestClient(app)

    class Client:
        def __init__(self, host="203.0.113.7"):
            self.headers = {"X-Forwarded-For": host}

        def post(self, path, **kwargs):
            return http.post(path, headers=self.headers, **kwargs)

        def get(self, path, **kwargs):
            return http.get(path, headers=self.headers, **kwargs)

    yield Client
    settings.trust_proxy_header = trusted
    app.dependency_overrides.clear()


# --- the window itself ------------------------------------------------------
#
# check() takes `now` explicitly, so expiry is testable without sleeping.

def test_the_window_allows_up_to_the_limit_then_refuses():
    window = SlidingWindow(limit=3, window_seconds=60)
    assert [window.check("ip", now=100.0) for _ in range(3)] == [None, None, None]
    assert window.check("ip", now=100.0) == 60


def test_a_hit_leaving_the_window_frees_a_slot():
    window = SlidingWindow(limit=2, window_seconds=60)
    window.check("ip", now=100.0)
    window.check("ip", now=130.0)
    assert window.check("ip", now=150.0) == 10   # wait for the 100.0 hit to age out
    assert window.check("ip", now=161.0) is None


def test_refusals_do_not_extend_the_penalty():
    """A client hammering the endpoint must still come back after one window."""
    window = SlidingWindow(limit=1, window_seconds=60)
    window.check("ip", now=100.0)
    for t in range(101, 160):
        assert window.check("ip", now=float(t)) is not None
    assert window.check("ip", now=161.0) is None


def test_keys_are_counted_separately():
    window = SlidingWindow(limit=1, window_seconds=60)
    assert window.check("a", now=100.0) is None
    assert window.check("b", now=100.0) is None
    assert window.check("a", now=100.0) is not None


def test_a_limit_of_zero_is_off():
    window = SlidingWindow(limit=0, window_seconds=60)
    assert all(window.check("ip", now=100.0) is None for _ in range(50))


def test_tracked_keys_are_bounded():
    """The key is client-controlled, so the dict must not grow with it."""
    window = SlidingWindow(limit=5, window_seconds=60, max_keys=10)
    for i in range(500):
        window.check(f"ip-{i}", now=100.0)
    assert len(window._hits) <= 10


# --- the two limits together -----------------------------------------------

def test_the_global_limit_catches_what_per_ip_misses():
    limiter = RateLimiter(per_ip=100, per_ip_window=60, overall=2, overall_window=3600)
    limiter.check("ip-1", now=100.0)
    limiter.check("ip-2", now=100.0)
    with pytest.raises(RateLimited) as caught:
        limiter.check("ip-3", now=100.0)
    assert caught.value.scope == "global"
    assert caught.value.retry_after == 3600


def test_one_abusive_client_cannot_spend_the_global_window():
    """Its refused requests are rejected per-IP and never reach the global count."""
    limiter = RateLimiter(per_ip=2, per_ip_window=60, overall=5, overall_window=3600)
    for _ in range(2):
        limiter.check("flooder", now=100.0)
    for _ in range(50):
        with pytest.raises(RateLimited) as caught:
            limiter.check("flooder", now=100.0)
        assert caught.value.scope == "per_ip"
    # three of the five global slots are still there for everybody else
    for i in range(3):
        limiter.check(f"other-{i}", now=100.0)


# --- through the API --------------------------------------------------------

def test_over_the_limit_returns_the_error_contract(tight_limits, limited_client, sample_tax_question):
    tight_limits(per_ip=2, overall=0)
    client = limited_client()
    for _ in range(2):
        assert client.post("/api/v1/tax/ask", json=sample_tax_question).status_code == 200

    response = client.post("/api/v1/tax/ask", json=sample_tax_question)
    assert response.status_code == 429
    body = response.json()
    assert body["error_code"] == "RATE_LIMITED"
    assert int(response.headers["Retry-After"]) > 0
    # which limit tripped is a hint about how to tune an attack — logged, not returned
    assert "global" not in body["detail"] and "per_ip" not in body["detail"]


def test_a_refused_request_costs_nothing(tight_limits, limited_client, fake_llm, sample_tax_question):
    """The whole point of the limit: over it, no provider call is made."""
    tight_limits(per_ip=1, overall=0)
    client = limited_client()
    client.post("/api/v1/tax/ask", json=sample_tax_question)
    calls_after_one_answer = len(fake_llm.calls)

    assert client.post("/api/v1/tax/ask", json=sample_tax_question).status_code == 429
    assert len(fake_llm.calls) == calls_after_one_answer


def test_one_client_over_the_limit_does_not_block_another(tight_limits, limited_client, sample_tax_question):
    tight_limits(per_ip=1, overall=0)
    flooder = limited_client("203.0.113.7")
    bystander = limited_client("198.51.100.4")
    flooder.post("/api/v1/tax/ask", json=sample_tax_question)

    assert flooder.post("/api/v1/tax/ask", json=sample_tax_question).status_code == 429
    assert bystander.post("/api/v1/tax/ask", json=sample_tax_question).status_code == 200


def test_health_is_not_limited(tight_limits, limited_client):
    """It is the Render health check, and it spends nothing."""
    tight_limits(per_ip=1, overall=1)
    client = limited_client()
    assert all(client.get("/api/v1/tax/health").status_code == 200 for _ in range(5))


def test_a_refusal_is_logged_without_the_address(tight_limits, limited_client, caplog, sample_tax_question):
    tight_limits(per_ip=1, overall=0)
    client = limited_client("203.0.113.7")
    client.post("/api/v1/tax/ask", json=sample_tax_question)
    with caplog.at_level("WARNING"):
        client.post("/api/v1/tax/ask", json=sample_tax_question)
    logged = str([r.msg for r in caplog.records])
    assert "rate_limited" in logged
    assert "203.0.113.7" not in logged      # the client is logged as a hash


# --- who a request is counted against --------------------------------------

class FakeRequest:
    def __init__(self, host, forwarded=None):
        self.client = type("Client", (), {"host": host})()
        self.headers = {"X-Forwarded-For": forwarded} if forwarded else {}


@pytest.fixture
def proxy_trust():
    """Flip TRUST_PROXY_HEADER on the cached settings, then restore it."""
    settings = get_settings()
    original = settings.trust_proxy_header

    def apply(value: bool):
        settings.trust_proxy_header = value

    yield apply
    settings.trust_proxy_header = original


def test_the_peer_address_is_the_key_by_default(proxy_trust):
    proxy_trust(False)
    # untrusted, so the header is ignored: otherwise a client would pick its own bucket
    assert client_key(FakeRequest("10.0.0.1", forwarded="1.1.1.1")) == "10.0.0.1"


def test_behind_a_trusted_proxy_the_rightmost_forwarded_entry_wins(proxy_trust):
    proxy_trust(True)
    # a client may prepend anything; only the last entry was appended by the proxy
    assert client_key(FakeRequest("10.0.0.1", forwarded="9.9.9.9, 203.0.113.7")) == "203.0.113.7"


def test_a_missing_forwarded_header_falls_back_to_the_peer(proxy_trust):
    proxy_trust(True)
    assert client_key(FakeRequest("10.0.0.1")) == "10.0.0.1"
