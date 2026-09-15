"""Request limits for the endpoint that costs money.

`/ask` makes at least two provider calls (analysis + generation), so an
unlimited public endpoint is a denial-of-wallet rather than a performance
problem: CORS keeps a *browser* on another origin out, but nothing stops a
`curl` loop, and the bill is real either way.

Two windows, because they answer different attacks:

  per-IP   — stops one noisy client, and is generous enough that a person
             reading answers will never see it;
  global   — the actual budget ceiling. A handful of IPs defeats any per-IP
             number, so without this the first limit is a speed bump.

Both are in-process and therefore per-worker: with N uvicorn workers the
effective limits are N times these numbers. That is the right trade for the
single-instance deployment this ships as, and the reason the global window is
set well below what the budget can absorb. A multi-instance deployment wants
the counters in Redis behind this same `check()` interface.
"""

import math
import time
from collections import OrderedDict, deque

import structlog
from fastapi import Request

logger = structlog.get_logger(__name__)

# Distinct keys held at once. Bounded because the key is client-controlled: an
# attacker rotating source addresses would otherwise grow this dict without
# limit. Eviction is least-recently-seen, so it only ever discards keys that
# have stopped sending — and a key that reappears starts from an empty window,
# which is the same position it would be in after waiting out the window.
MAX_TRACKED_KEYS = 4096


class RateLimited(Exception):
    """Raised by the dependency; turned into a 429 by the handler in main.py."""

    def __init__(self, scope: str, retry_after: int):
        self.scope = scope            # "per_ip" | "global" — logged, not returned
        self.retry_after = retry_after
        super().__init__(f"rate limited ({scope}), retry after {retry_after}s")


class SlidingWindow:
    """Hit counter per key over a moving window. A limit of 0 or less is off."""

    def __init__(self, limit: int, window_seconds: int, max_keys: int = MAX_TRACKED_KEYS):
        self.limit = limit
        self.window = window_seconds
        self.max_keys = max_keys
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()

    def check(self, key: str, now: float) -> int | None:
        """Record a hit and return None, or the seconds to wait if over the limit.

        A refused request is *not* recorded. Otherwise a client hammering the
        endpoint would keep pushing its own window forward and never come back
        under the limit, which turns a throttle into a ban.
        """
        if self.limit <= 0:
            return None

        hits = self._hits.get(key)
        if hits is None:
            hits = self._hits[key] = deque()
        self._hits.move_to_end(key)

        cutoff = now - self.window
        while hits and hits[0] <= cutoff:
            hits.popleft()

        if len(hits) >= self.limit:
            # the oldest hit still in the window is the first one to expire
            return max(1, math.ceil(hits[0] + self.window - now))

        hits.append(now)
        while len(self._hits) > self.max_keys:
            self._hits.popitem(last=False)
        return None

    def reset(self) -> None:
        self._hits.clear()


class RateLimiter:
    """The pair of windows guarding `/ask`."""

    GLOBAL_KEY = "*"

    def __init__(self, per_ip: int, per_ip_window: int, overall: int, overall_window: int):
        self.per_ip = SlidingWindow(per_ip, per_ip_window)
        self.overall = SlidingWindow(overall, overall_window)

    def check(self, client_key: str, now: float | None = None) -> None:
        """Raise RateLimited if this request should be refused."""
        now = time.monotonic() if now is None else now
        # Per-IP first, so one abusive client is refused on its own bucket
        # without its refused requests counting against the global window —
        # otherwise a single loop could lock everyone else out for the hour.
        retry_after = self.per_ip.check(client_key, now)
        if retry_after is not None:
            raise RateLimited("per_ip", retry_after)
        retry_after = self.overall.check(self.GLOBAL_KEY, now)
        if retry_after is not None:
            raise RateLimited("global", retry_after)

    def reset(self) -> None:
        self.per_ip.reset()
        self.overall.reset()


_limiter: RateLimiter | None = None


def get_limiter() -> RateLimiter:
    """The process-wide limiter, built from settings on first use."""
    global _limiter
    if _limiter is None:
        from core.config import get_settings

        settings = get_settings()
        _limiter = RateLimiter(
            per_ip=settings.rate_limit_per_ip,
            per_ip_window=settings.rate_limit_per_ip_window_seconds,
            overall=settings.rate_limit_global,
            overall_window=settings.rate_limit_global_window_seconds,
        )
    return _limiter


def client_key(request: Request) -> str:
    """Which client this request is counted against.

    Behind a proxy every request arrives from the proxy, so `request.client.host`
    would put the whole internet in one bucket. `X-Forwarded-For` is only read
    when `TRUST_PROXY_HEADER` says there is exactly one trusted proxy in front,
    and then only its *rightmost* entry: a client can prepend whatever it likes
    to that header, but the entry the proxy appends is the address it actually
    received the connection from.
    """
    from core.config import get_settings

    if get_settings().trust_proxy_header:
        forwarded = request.headers.get("X-Forwarded-For", "")
        entries = [e.strip() for e in forwarded.split(",") if e.strip()]
        if entries:
            return entries[-1]
    client = getattr(request, "client", None)
    return getattr(client, "host", None) or "unknown"


async def enforce_rate_limit(request: Request) -> None:
    """FastAPI dependency guarding the endpoints that spend money.

    `async` on purpose: it runs on the event loop, so the counters are touched
    by one task at a time and need no lock. A sync dependency would be handed to
    the threadpool and this would become a race. The `Request` annotation is
    load-bearing too — without it FastAPI reads the parameter as a query field
    and every /ask fails validation.
    """
    key = client_key(request)
    try:
        get_limiter().check(key)
    except RateLimited as exc:
        # The key is an IP, so it is logged as a hash — enough to tell one client
        # from another in the logs without recording who they are.
        from core import security

        logger.warning(
            "rate_limited",
            path=request.url.path,
            scope=exc.scope,
            client=security.fingerprint(key),
            retry_after=exc.retry_after,
        )
        raise
