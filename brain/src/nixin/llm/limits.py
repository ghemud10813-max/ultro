"""Local rate limiting so Nixin stays inside free tiers *before* the provider says no.

Each (candidate, key) has sliding one-minute windows for requests and tokens plus
daily counters, and a cooldown set from 429 / retry-after / reset headers.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from nixin.config import LimitConfig


@dataclass
class Bucket:
    limit: LimitConfig
    req_times: deque = field(default_factory=deque)
    tok_events: deque = field(default_factory=deque)  # (ts, tokens)
    day: str = ""
    day_requests: int = 0
    day_tokens: int = 0
    cooldown_until: float = 0.0
    failures: int = 0

    def _roll(self, now: float) -> None:
        while self.req_times and now - self.req_times[0] > 60:
            self.req_times.popleft()
        while self.tok_events and now - self.tok_events[0][0] > 60:
            self.tok_events.popleft()
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        if today != self.day:
            self.day, self.day_requests, self.day_tokens = today, 0, 0

    def wait_time(self, est_tokens: int, now: float | None = None) -> float:
        """Seconds until a request of ~est_tokens may be sent (0 = now, inf = not today)."""
        now = now or time.time()
        self._roll(now)
        if self.day_requests >= self.limit.rpd or self.day_tokens + est_tokens > self.limit.tpd:
            return float("inf")
        wait = max(0.0, self.cooldown_until - now)
        if len(self.req_times) >= self.limit.rpm:
            wait = max(wait, 60 - (now - self.req_times[0]) + 0.05)
        used = sum(t for _, t in self.tok_events)
        if est_tokens > self.limit.tpm:
            # a single request bigger than the per-minute budget can never fit
            return float("inf") if self.limit.tpm < est_tokens else wait
        if used + est_tokens > self.limit.tpm and self.tok_events:
            # wait until enough old events fall out of the window
            need = used + est_tokens - self.limit.tpm
            freed = 0
            for ts, t in self.tok_events:
                freed += t
                if freed >= need:
                    wait = max(wait, 60 - (now - ts) + 0.05)
                    break
        return wait

    def record(self, tokens: int, now: float | None = None) -> None:
        now = now or time.time()
        self._roll(now)
        self.req_times.append(now)
        self.tok_events.append((now, tokens))
        self.day_requests += 1
        self.day_tokens += tokens
        self.failures = 0

    def correct_tokens(self, estimated: int, actual: int) -> None:
        """Replace the estimate recorded at send time with the real usage."""
        if self.tok_events and actual > 0:
            ts, _ = self.tok_events[-1]
            self.tok_events[-1] = (ts, actual)
            self.day_tokens += actual - estimated

    def cool(self, seconds: float) -> None:
        self.cooldown_until = max(self.cooldown_until, time.time() + max(1.0, seconds))

    def fail(self) -> None:
        """Circuit breaker for transient errors: 5s, 10s, 20s ... up to 5 minutes."""
        self.failures += 1
        self.cool(min(300.0, 5.0 * (2 ** (self.failures - 1))))

    def seed_daily(self, requests: int, tokens: int) -> None:
        self._roll(time.time())
        self.day_requests = max(self.day_requests, requests)
        self.day_tokens = max(self.day_tokens, tokens)


def estimate_tokens(messages: list[dict], tools: list[dict] | None = None, max_tokens: int = 0) -> int:
    """Cheap token estimate (~3.3 chars/token for mixed Hinglish/JSON) + reply budget."""
    import json

    chars = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            chars += len(c)
        elif isinstance(c, list):
            for part in c:
                if part.get("type") == "text":
                    chars += len(part.get("text", ""))
                elif part.get("type") == "image_url":
                    chars += 3000  # images are billed roughly like ~1k tokens
        if m.get("tool_calls"):
            chars += len(json.dumps(m["tool_calls"]))
    if tools:
        chars += len(json.dumps(tools))
    return int(chars / 3.3) + 20 * len(messages) + max_tokens // 2
