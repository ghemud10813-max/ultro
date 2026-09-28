from __future__ import annotations

import asyncio
import json
from collections import deque

import httpx
import pytest

from nixin.app import NixinApp
from nixin.config import NixinConfig, PcConfig
from nixin.core.events import EventBus
from nixin.core.store import Store
from nixin.sim.client import DeviceIdentity, PhoneClient, parse_pairing_uri
from nixin.sim.phone_sim import SimPhone


@pytest.fixture
def cfg(tmp_path) -> NixinConfig:
    c = NixinConfig(pc=PcConfig(name="Test-PC", data_dir=str(tmp_path / "data")))
    c.voice.enabled = False
    c.dashboard.enabled = False
    c.bridge.inbox_dir = str(tmp_path / "inbox")
    c.bridge.clipboard_on_share = False
    c.notifications.toast_on_pc = False
    return c


@pytest.fixture
def store() -> Store:
    s = Store(":memory:")
    yield s
    s.close()


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


class ScriptedLLM:
    """Fake OpenAI-compatible endpoint. Each role has a queue of replies (tool calls or text)."""

    def __init__(self) -> None:
        self.queues: dict[str, deque] = {"classifier": deque(), "planner": deque(), "verifier": deque(), "vision": deque()}
        self.requests: list[dict] = []

    def role_of(self, body: dict) -> str:
        names = {t["function"]["name"] for t in body.get("tools") or []}
        if "phone_task" in names:
            return "classifier"
        if "tap" in names:
            return "planner"
        if any(isinstance(m.get("content"), list) for m in body["messages"]):
            return "vision"
        return "verifier"

    def tool(self, _role: str, _name: str, **args) -> None:
        self.queues[_role].append({"tool_calls": [{"id": "c1", "type": "function",
                                                   "function": {"name": _name, "arguments": json.dumps(args)}}]})

    def text(self, role: str, content: str) -> None:
        self.queues[role].append({"content": content})

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": m} for m in ["openai/gpt-oss-20b", "openai/gpt-oss-120b",
                                                                          "qwen/qwen3.8-27b", "qwen/qwen3-32b"]]})
        body = json.loads(request.content)
        role = self.role_of(body)
        self.requests.append({"role": role, "model": body["model"], "body": body})
        if not self.queues[role]:
            return httpx.Response(200, json=_msg({"content": '{"done": true, "reason": "ok"}'} if role == "verifier"
                                                 else {"content": "ok"}))
        return httpx.Response(200, json=_msg(self.queues[role].popleft()))


def _msg(m: dict) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": m.get("content"),
                                     **({"tool_calls": m["tool_calls"]} if "tool_calls" in m else {})},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 500, "completion_tokens": 40}}


@pytest.fixture
async def world(cfg, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    for k in ("CEREBRAS_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY", "CLOUDFLARE_API_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    cfg.link.host, cfg.link.port = "127.0.0.1", 0
    cfg.assistant.confirm_timeout_seconds = 3
    llm = ScriptedLLM()
    http = httpx.AsyncClient(transport=httpx.MockTransport(llm.handler))
    app = NixinApp(cfg, http=http, db_path=":memory:")
    await app.start(with_voice=False, with_dashboard=False)
    sim = SimPhone()
    client = PhoneClient(DeviceIdentity.new(), sim.handle)
    await client.pair(parse_pairing_uri(app.new_pairing().uri))
    serve = asyncio.create_task(client.serve())
    assert await app.phone.wait_connected(5)
    await asyncio.sleep(0.2)  # initial status + app list sync
    yield app, sim, client, llm
    serve.cancel()
    await client.close()
    await app.stop()
