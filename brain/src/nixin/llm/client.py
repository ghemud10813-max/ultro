"""Minimal OpenAI-compatible chat client (Groq, Cerebras, OpenRouter, Gemini, Cloudflare, Ollama).

We deliberately avoid provider SDKs: one small httpx client is easier to reason
about, and "OpenAI-compatible" providers differ just enough (errors, headers,
tool support) that we want full control over the raw exchange.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict
    raw_arguments: str = ""


@dataclass
class ChatResult:
    content: str
    tool_calls: list[ToolCall]
    prompt_tokens: int
    completion_tokens: int
    candidate: str = ""
    finish_reason: str | None = None
    headers: dict[str, str] = field(default_factory=dict)

    def first_json(self) -> dict | None:
        return extract_json(self.content)


class LlmError(Exception):
    kind = "error"

    def __init__(self, message: str, *, status: int | None = None, retry_after: float | None = None,
                 body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after
        self.body = body


class RateLimited(LlmError):
    kind = "rate_limited"


class AuthFailed(LlmError):
    kind = "auth"


class ModelUnavailable(LlmError):
    kind = "unavailable"


class ToolsUnsupported(LlmError):
    kind = "no_tools"


class InvalidOutput(LlmError):
    kind = "invalid_output"


class Transient(LlmError):
    kind = "transient"


def _parse_duration(v: str | None) -> float | None:
    """Parse '7.66s', '2m59.56s', '120ms', '30' -> seconds."""
    if not v:
        return None
    v = v.strip()
    try:
        return float(v)
    except ValueError:
        pass
    total, found = 0.0, False
    for num, unit in re.findall(r"([\d.]+)(ms|h|m|s)", v):
        found = True
        n = float(num)
        total += {"ms": n / 1000, "h": n * 3600, "m": n * 60, "s": n}[unit]
    return total if found else None


def extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of a model reply (tolerates ```json fences and chatter)."""
    if not text:
        return None
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
    candidates = [m.group(1)] if m else []
    start = text.find("{")
    if start >= 0:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                esc = (ch == "\\") and not esc
                if ch == '"' and not esc:
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : i + 1])
                    break
    for c in candidates:
        try:
            v = json.loads(c)
            if isinstance(v, dict):
                return v
        except json.JSONDecodeError:
            continue
    return None


async def chat_completion(
    http: httpx.AsyncClient,
    *,
    base_url: str,
    api_key: str | None,
    model: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    tool_choice: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 1024,
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 45.0,
) -> ChatResult:
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = tool_choice or "auto"
        body["parallel_tool_calls"] = True
    if extra:
        body.update(extra)
    h = {"Content-Type": "application/json", **(headers or {})}
    if api_key:
        h["Authorization"] = f"Bearer {api_key}"

    try:
        r = await http.post(base_url.rstrip("/") + "/chat/completions", json=body, headers=h, timeout=timeout)
    except (httpx.TimeoutException, httpx.TransportError) as e:
        raise Transient(f"network: {e!r}") from e

    hdrs = {k.lower(): v for k, v in r.headers.items()}
    if r.status_code >= 400:
        text = r.text[:2000]
        low = text.lower()
        retry = _parse_duration(hdrs.get("retry-after")) or _parse_duration(hdrs.get("x-ratelimit-reset-tokens"))
        if r.status_code == 429 or "rate limit" in low or "rate_limit" in low:
            raise RateLimited("rate limited", status=r.status_code, retry_after=retry, body=text)
        if r.status_code in (401, 403) and "model" not in low:
            raise AuthFailed("authentication failed", status=r.status_code, body=text)
        if r.status_code == 404 or "model_not_found" in low or "does not exist" in low or "decommissioned" in low \
                or ("model" in low and ("not found" in low or "not available" in low or "no access" in low)):
            raise ModelUnavailable("model unavailable", status=r.status_code, body=text)
        if "tool_use_failed" in low or "failed_generation" in low or "parse" in low and "tool" in low:
            raise InvalidOutput("model produced an invalid tool call", status=r.status_code, body=text)
        if tools and ("tool" in low or "function" in low) and ("support" in low or "not enabled" in low):
            raise ToolsUnsupported("tools not supported", status=r.status_code, body=text)
        if r.status_code >= 500:
            raise Transient(f"server error {r.status_code}", status=r.status_code, body=text)
        if r.status_code == 413 or "context" in low and "length" in low or "too large" in low:
            raise InvalidOutput("request too large for this model", status=r.status_code, body=text)
        raise LlmError(f"HTTP {r.status_code}", status=r.status_code, body=text)

    try:
        data = r.json()
        choice = data["choices"][0]
        msg = choice.get("message") or {}
    except (ValueError, KeyError, IndexError) as e:
        raise Transient(f"bad response: {r.text[:300]}") from e

    calls: list[ToolCall] = []
    for i, tc in enumerate(msg.get("tool_calls") or []):
        fn = tc.get("function") or {}
        raw = fn.get("arguments") or "{}"
        try:
            args = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except json.JSONDecodeError:
            args = extract_json(raw) or {}
            if not args and raw.strip() not in ("", "{}"):
                raise InvalidOutput(f"unparseable tool arguments: {raw[:200]}") from None
        if not isinstance(args, dict):
            args = {}
        calls.append(ToolCall(tc.get("id") or f"call_{i}", str(fn.get("name", "")), args, raw if isinstance(raw, str) else ""))

    usage = data.get("usage") or {}
    content = msg.get("content") or ""
    if isinstance(content, list):  # some providers return content parts
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ChatResult(
        content=re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip(),
        tool_calls=calls,
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        finish_reason=choice.get("finish_reason"),
        headers={k: v for k, v in hdrs.items() if k.startswith("x-ratelimit") or k == "retry-after"},
    )


async def list_models(http: httpx.AsyncClient, base_url: str, api_key: str | None,
                      headers: dict[str, str] | None = None) -> set[str] | None:
    h = dict(headers or {})
    if api_key:
        h["Authorization"] = f"Bearer {api_key}"
    try:
        r = await http.get(base_url.rstrip("/") + "/models", headers=h, timeout=15)
        if r.status_code != 200:
            return None
        data = r.json().get("data") or r.json().get("models") or []
        ids = set()
        for m in data:
            mid = m.get("id") or m.get("name") or ""
            ids.add(mid)
            if mid.startswith("models/"):
                ids.add(mid.removeprefix("models/"))
        return ids
    except Exception:
        return None
