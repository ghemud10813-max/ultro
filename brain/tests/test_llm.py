"""LLM layer: client error mapping, JSON extraction, rate buckets, gateway fallback/privacy."""

from __future__ import annotations

import json
import time

import httpx
import pytest

from nixin.config import LimitConfig, NixinConfig
from nixin.llm.client import ModelUnavailable, RateLimited, _parse_duration, chat_completion, extract_json
from nixin.llm.gateway import Gateway, NoCandidate
from nixin.llm.limits import Bucket, estimate_tokens


def _ok(content="hi", tool=None):
    msg = {"role": "assistant", "content": content}
    if tool:
        msg["tool_calls"] = [{"id": "1", "type": "function", "function": {"name": tool[0], "arguments": json.dumps(tool[1])}}]
    return httpx.Response(200, json={"choices": [{"message": msg, "finish_reason": "stop"}],
                                     "usage": {"prompt_tokens": 10, "completion_tokens": 5}},
                          headers={"x-ratelimit-remaining-tokens": "7000"})


def test_parse_duration():
    assert _parse_duration("7.66s") == pytest.approx(7.66)
    assert _parse_duration("2m59.5s") == pytest.approx(179.5)
    assert _parse_duration("120ms") == pytest.approx(0.12)
    assert _parse_duration("30") == 30


def test_extract_json():
    assert extract_json('sure! ```json\n{"done": true}\n``` ok') == {"done": True}
    assert extract_json('<think>hmm {"x":1}</think>{"done": false, "reason": "a {b}"}') == {"done": False, "reason": "a {b}"}
    assert extract_json("no json") is None


async def test_client_maps_errors_and_tool_calls():
    def h(req):
        body = json.loads(req.content)
        if body["model"] == "gone":
            return httpx.Response(404, json={"error": {"message": "The model `gone` does not exist"}})
        if body["model"] == "busy":
            return httpx.Response(429, headers={"retry-after": "12"}, json={"error": {"message": "Rate limit reached"}})
        return _ok(tool=("tap", {"id": 3}))

    async with httpx.AsyncClient(transport=httpx.MockTransport(h)) as http:
        res = await chat_completion(http, base_url="http://x/v1", api_key="k", model="ok", messages=[])
        assert res.tool_calls[0].name == "tap" and res.tool_calls[0].arguments == {"id": 3}
        with pytest.raises(ModelUnavailable):
            await chat_completion(http, base_url="http://x/v1", api_key="k", model="gone", messages=[])
        with pytest.raises(RateLimited) as e:
            await chat_completion(http, base_url="http://x/v1", api_key="k", model="busy", messages=[])
        assert e.value.retry_after == 12


def test_bucket_limits():
    b = Bucket(LimitConfig(rpm=2, tpm=1000, rpd=3, tpd=10_000))
    now = time.time()
    assert b.wait_time(100, now) == 0
    b.record(100, now)
    b.record(100, now)
    assert b.wait_time(100, now) > 50  # rpm hit
    assert b.wait_time(100, now + 61) == 0
    b.record(100, now + 61)
    assert b.wait_time(100, now + 200) == float("inf")  # rpd hit
    b2 = Bucket(LimitConfig(rpm=100, tpm=1000, rpd=100, tpd=100_000))
    b2.record(900, now)
    assert b2.wait_time(300, now + 1) > 50  # tpm hit
    assert b2.wait_time(5000, now) == float("inf")  # never fits


def test_estimate_tokens():
    n = estimate_tokens([{"role": "user", "content": "x" * 3300}], None, 100)
    assert 1000 < n < 1200


async def test_gateway_skips_keyless_and_respects_privacy(monkeypatch):
    for k in ("GROQ_API_KEY", "CEREBRAS_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "CLOUDFLARE_API_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CEREBRAS_API_KEY", "c")
    seen = []

    def h(req):
        seen.append((str(req.url), json.loads(req.content)["model"]))
        return _ok("yo")

    cfg = NixinConfig()
    gw = Gateway(cfg, http=httpx.AsyncClient(transport=httpx.MockTransport(h)))
    res = await gw.complete("classifier", [{"role": "user", "content": "hi"}])
    assert res.candidate == "cerebras:gpt-oss-120b" and "cerebras" in seen[0][0]
    cfg.privacy.cloud_llm = False
    with pytest.raises(NoCandidate):
        await gw.complete("classifier", [{"role": "user", "content": "hi"}])
    await gw.aclose()


async def test_gateway_key_pool_rotates_on_bad_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "bad,good")

    def h(req):
        if req.headers["authorization"] == "Bearer bad":
            return httpx.Response(401, json={"error": {"message": "Invalid API Key"}})
        return _ok("fine")

    cfg = NixinConfig()
    cfg.models["classifier"] = ["groq:openai/gpt-oss-20b"]
    gw = Gateway(cfg, http=httpx.AsyncClient(transport=httpx.MockTransport(h)))
    res = await gw.complete("classifier", [{"role": "user", "content": "hi"}])
    assert res.content == "fine"
    assert gw.providers["groq"].bad_keys == {0}
    await gw.aclose()


async def test_gateway_marks_missing_model_and_falls_through(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")

    def h(req):
        if json.loads(req.content)["model"] == "qwen/qwen3.8-27b":
            return httpx.Response(404, json={"error": {"message": "model_not_found"}})
        return _ok('{"done": true}')

    cfg = NixinConfig()
    gw = Gateway(cfg, http=httpx.AsyncClient(transport=httpx.MockTransport(h)))
    res = await gw.complete("verifier", [{"role": "user", "content": "x"}])
    assert res.candidate == "groq:qwen/qwen3-32b"
    assert gw.candidates["groq:qwen/qwen3.8-27b"].available is False
    await gw.aclose()
