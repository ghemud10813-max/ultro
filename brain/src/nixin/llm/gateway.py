"""Provider gateway: roles -> ordered candidates across providers and keys.

``await gateway.complete("planner", messages, tools=...)`` picks the first candidate
that is configured, has a key, is not cooling down and fits the local free-tier
budget; on rate limits / outages it moves to the next key, then the next candidate.
Paid usage is impossible by construction: only the free candidates you list are used.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

import httpx

from nixin.config import NixinConfig, get_secret, get_secret_pool
from nixin.core.events import EventBus
from nixin.core.store import Store
from nixin.llm.client import (
    AuthFailed,
    ChatResult,
    InvalidOutput,
    LlmError,
    ModelUnavailable,
    RateLimited,
    ToolsUnsupported,
    Transient,
    chat_completion,
    list_models,
)
from nixin.llm.limits import Bucket, estimate_tokens

log = logging.getLogger("nixin.llm")

LOCAL_PROVIDERS = {"ollama"}
ROLE_SETTINGS = {
    # role: (temperature, max_tokens, reasoning_effort for gpt-oss models)
    "classifier": (0.1, 700, "low"),
    "planner": (0.1, 900, "low"),
    "verifier": (0.0, 400, "low"),
    "vision": (0.1, 700, None),
}


class NoCandidate(LlmError):
    kind = "no_candidate"


class PrivacyBlocked(LlmError):
    kind = "privacy"


@dataclass
class Candidate:
    spec: str  # "provider:model"
    provider: str
    model: str
    available: bool | None = None  # None = unknown until first use / probe
    tools_ok: bool = True
    last_error: str = ""


@dataclass
class ProviderState:
    name: str
    base_url: str
    keys: list[str]
    headers: dict[str, str]
    timeout: float
    enabled: bool
    models: set[str] | None = None
    bad_keys: set[int] = field(default_factory=set)


class Gateway:
    def __init__(self, cfg: NixinConfig, store: Store | None = None, bus: EventBus | None = None,
                 http: httpx.AsyncClient | None = None) -> None:
        self.cfg = cfg
        self.store = store
        self.bus = bus
        self.http = http or httpx.AsyncClient(timeout=60)
        self.providers: dict[str, ProviderState] = {}
        self.buckets: dict[tuple[str, int], Bucket] = {}
        self.candidates: dict[str, Candidate] = {}
        self.reload()

    # ------------------------------------------------------------------ setup
    def reload(self) -> None:
        self.providers.clear()
        for name, p in self.cfg.providers.items():
            keys = get_secret_pool(p.key_env) if p.key_env else [""]
            base = p.base_url
            if "{account_id}" in base:
                acct = get_secret(p.account_env) or ""
                if not acct:
                    keys = []
                base = base.replace("{account_id}", acct)
            self.providers[name] = ProviderState(name, base, keys, dict(p.headers), p.timeout_seconds, p.enabled)
        for specs in self.cfg.models.values():
            for spec in specs:
                if spec not in self.candidates and ":" in spec:
                    prov, model = spec.split(":", 1)
                    self.candidates[spec] = Candidate(spec, prov, model)
        usage = self.store.usage_today() if self.store else {}
        for spec, row in usage.items():
            b = self._bucket(spec, 0)
            b.seed_daily(row["requests"], row["prompt_tokens"] + row["completion_tokens"])

    def _bucket(self, spec: str, key_idx: int) -> Bucket:
        k = (spec, key_idx)
        if k not in self.buckets:
            self.buckets[k] = Bucket(self.cfg.limit_for(spec))
        return self.buckets[k]

    def configured(self, spec: str) -> bool:
        c = self.candidates.get(spec)
        if not c:
            return False
        p = self.providers.get(c.provider)
        return bool(p and p.enabled and p.keys and len(p.bad_keys) < len(p.keys))

    def role_ready(self, role: str) -> bool:
        return any(self.configured(s) and self.candidates[s].available is not False for s in self.cfg.models.get(role, []))

    def any_ready(self) -> bool:
        return any(self.role_ready(r) for r in self.cfg.models)

    # ------------------------------------------------------------------ probing
    async def probe(self) -> dict[str, dict]:
        """Check which configured models exist for each provider (GET /models)."""
        report: dict[str, dict] = {}
        for name, p in self.providers.items():
            if not (p.enabled and p.keys):
                report[name] = {"status": "no key" if p.enabled else "disabled"}
                continue
            ids = await list_models(self.http, p.base_url, p.keys[0] or None, p.headers)
            p.models = ids
            report[name] = {"status": "ok" if ids is not None else "unreachable", "models": len(ids or [])}
        for c in self.candidates.values():
            p = self.providers.get(c.provider)
            if p and p.models is not None:
                c.available = c.model in p.models
                if not c.available:
                    c.last_error = "not in provider model list"
        return report

    def status(self) -> dict:
        roles = {}
        for role, specs in self.cfg.models.items():
            roles[role] = [
                {
                    "spec": s,
                    "configured": self.configured(s),
                    "available": self.candidates[s].available if s in self.candidates else None,
                    "error": self.candidates[s].last_error if s in self.candidates else "",
                    "cooldown": max(0.0, self._bucket(s, 0).cooldown_until - time.time()),
                    "today": {"requests": self._bucket(s, 0).day_requests, "tokens": self._bucket(s, 0).day_tokens},
                }
                for s in specs
            ]
        return {
            "providers": {n: {"keys": len(p.keys), "enabled": p.enabled, "bad_keys": len(p.bad_keys)}
                          for n, p in self.providers.items()},
            "roles": roles,
        }

    # ------------------------------------------------------------------ calls
    async def complete(
        self,
        role: str,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        has_image: bool = False,
        deadline: float | None = None,
        max_wait: float = 12.0,
    ) -> ChatResult:
        specs = self.cfg.models.get(role) or []
        if not specs:
            raise NoCandidate(f"No models configured for role {role!r}")
        temp_default, max_default, effort = ROLE_SETTINGS.get(role, (0.2, 800, None))
        max_tokens = max_tokens or max_default
        temperature = temp_default if temperature is None else temperature
        est = estimate_tokens(messages, tools, max_tokens)
        errors: list[str] = []

        for _round in range(3):
            soonest = float("inf")
            for spec in specs:
                c = self.candidates.get(spec)
                if c is None or c.available is False or (tools and not c.tools_ok):
                    continue
                p = self.providers.get(c.provider)
                if not p or not p.enabled or not p.keys:
                    continue
                if c.provider not in LOCAL_PROVIDERS:
                    if not self.cfg.privacy.cloud_llm:
                        errors.append(f"{spec}: cloud LLM disabled in privacy settings")
                        continue
                    if has_image and not self.cfg.privacy.cloud_vision:
                        errors.append(f"{spec}: cloud vision disabled in privacy settings")
                        continue
                for key_idx, key in enumerate(p.keys):
                    if key_idx in p.bad_keys:
                        continue
                    bucket = self._bucket(spec, key_idx)
                    wait = bucket.wait_time(est)
                    if wait > 0:
                        soonest = min(soonest, wait)
                        continue
                    if deadline and time.time() > deadline:
                        raise NoCandidate("task deadline reached")
                    bucket.record(est)
                    extra = {}
                    if effort and "gpt-oss" in c.model:
                        extra["reasoning_effort"] = effort
                    try:
                        res = await chat_completion(
                            self.http, base_url=p.base_url, api_key=key or None, model=c.model,
                            messages=messages, tools=tools, tool_choice=tool_choice, temperature=temperature,
                            max_tokens=max_tokens, extra=extra, headers=p.headers, timeout=p.timeout,
                        )
                    except RateLimited as e:
                        bucket.cool(e.retry_after or 20.0)
                        self._note(spec, f"rate limited ({e.retry_after or '?'}s)", error=True)
                        errors.append(f"{spec}: rate limited")
                        continue
                    except AuthFailed:
                        p.bad_keys.add(key_idx)
                        self._note(spec, f"key #{key_idx + 1} rejected (401/403)", error=True)
                        errors.append(f"{spec}: bad key")
                        continue
                    except ModelUnavailable as e:
                        c.available, c.last_error = False, "model unavailable"
                        self._note(spec, "model unavailable — skipping", error=True)
                        errors.append(f"{spec}: unavailable ({e.body[:120]})")
                        break
                    except ToolsUnsupported:
                        c.tools_ok, c.last_error = False, "no tool calling"
                        errors.append(f"{spec}: no tool support")
                        break
                    except InvalidOutput:
                        # a malformed tool call is usually fixed by simply trying the next candidate
                        self._note(spec, "invalid tool output", error=True)
                        errors.append(f"{spec}: invalid output")
                        break
                    except Transient as e:
                        bucket.fail()
                        self._note(spec, f"transient error: {e}", error=True)
                        errors.append(f"{spec}: {e}")
                        break
                    except LlmError as e:
                        bucket.fail()
                        self._note(spec, f"error {e.status}: {e.body[:160]}", error=True)
                        errors.append(f"{spec}: HTTP {e.status}")
                        break
                    bucket.correct_tokens(est, res.prompt_tokens + res.completion_tokens)
                    self._apply_headers(bucket, res.headers)
                    c.available = True
                    c.last_error = ""
                    res.candidate = spec
                    if self.store:
                        self.store.add_usage(spec, res.prompt_tokens, res.completion_tokens)
                    if self.bus:
                        self.bus.emit("llm", role=role, candidate=spec, prompt=res.prompt_tokens,
                                      completion=res.completion_tokens)
                    return res
            # nothing usable right now: wait briefly if a candidate frees up soon
            if soonest <= max_wait and (not deadline or time.time() + soonest < deadline):
                if self.bus:
                    self.bus.emit("log", level="info", msg=f"{role}: waiting {soonest:.1f}s for free-tier budget")
                await asyncio.sleep(soonest)
                continue
            break

        if not any(self.configured(s) for s in specs):
            raise NoCandidate(
                f"No API key configured for any {role} model. Add GROQ_API_KEY (free) to .env — see docs/SETUP.md."
            )
        raise NoCandidate(f"All {role} models are busy or failing: " + "; ".join(errors[-4:]))

    def _apply_headers(self, bucket: Bucket, headers: dict[str, str]) -> None:
        """Use Groq-style x-ratelimit headers to avoid hitting the wall."""
        from nixin.llm.client import _parse_duration

        try:
            rem_tokens = headers.get("x-ratelimit-remaining-tokens")
            if rem_tokens is not None and int(float(rem_tokens)) < 300:
                bucket.cool(_parse_duration(headers.get("x-ratelimit-reset-tokens")) or 10)
            rem_req = headers.get("x-ratelimit-remaining-requests")
            if rem_req is not None and int(float(rem_req)) <= 0:
                bucket.cool(_parse_duration(headers.get("x-ratelimit-reset-requests")) or 60)
        except ValueError:
            pass

    def _note(self, spec: str, msg: str, error: bool = False) -> None:
        c = self.candidates.get(spec)
        if c and error:
            c.last_error = msg
        if error and self.store:
            self.store.add_usage(spec, 0, 0, error=True)
        if self.bus:
            self.bus.emit("log", level="warning" if error else "info", msg=f"LLM {spec}: {msg}")
        log.info("%s: %s", spec, msg)

    async def aclose(self) -> None:
        await self.http.aclose()
