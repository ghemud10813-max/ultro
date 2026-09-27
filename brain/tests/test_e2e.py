"""End-to-end: NixinApp + simulated phone over real TLS + scripted fake LLM."""

from __future__ import annotations

import asyncio
import json
from collections import deque

import httpx
import pytest

from nixin.app import NixinApp
from nixin.sim.client import DeviceIdentity, PhoneClient, parse_pairing_uri
from nixin.sim.phone_sim import SimPhone


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


async def test_router_commands_need_no_llm(world):
    app, sim, client, llm = world
    reply = await app.brain.handle("volume badha do")
    assert sim.volumes["media"][0] == 9 and "9/15" in reply
    await app.brain.handle("torch on karo aur volume full kar do")
    assert sim.torch is True and sim.volumes["media"][0] == 15
    await app.brain.handle("kal subah 6 baje ka alarm laga do")
    assert sim.alarms[-1]["hour"] == 6
    reply = await app.brain.handle("WhatsApp kholo")
    assert sim.screen_name == "wa_chats" and "WhatsApp" in reply
    reply = await app.brain.handle("instagram ki notification padho")
    assert "liked your photo" in reply
    assert llm.requests == []  # zero LLM calls


async def test_typed_whatsapp_message_sends_without_prompt(world):
    app, sim, client, llm = world
    reply = await app.brain.handle("WhatsApp pe Mummy ko bol main 10 min late hoon")
    assert sim.whatsapp_sent[-1]["text"] == "main 10 min late hoon"
    assert sim.whatsapp_sent[-1]["name"] == "Mummy"
    assert "bhej diya" in reply


async def test_voice_message_asks_and_respects_no(world):
    app, sim, client, llm = world
    task = asyncio.create_task(app.brain.handle("Priya ko whatsapp kar do ki call back karna", source="voice"))
    for _ in range(50):
        if app.gate.pending:
            break
        await asyncio.sleep(0.05)
    assert app.gate.pending
    app.gate.answer(None, "nahi")
    reply = await task
    assert sim.whatsapp_sent == [] and "nahi kiya" in reply.lower()


async def test_phone_answers_confirmation(world):
    app, sim, client, llm = world
    task = asyncio.create_task(app.brain.handle("Priya ko whatsapp kar do ki call back karna", source="phone_voice"))
    ask = None
    while ask is None:
        msg = await asyncio.wait_for(client.inbox.get(), 5)
        if msg["t"] == "ask":
            ask = msg
    await client.answer(ask["id"], "yes")
    await task
    assert sim.whatsapp_sent[-1]["text"] == "call back karna"


async def test_ambiguous_contact_is_clarified(world):
    app, sim, client, llm = world
    task = asyncio.create_task(app.brain.handle("Rahul ko call karo"))
    for _ in range(50):
        if app.gate.pending:
            break
        await asyncio.sleep(0.05)
    ask = app.gate.current
    assert ask.kind == "choose" and set(ask.options) == {"Rahul Sharma", "Rahul Verma"}
    app.gate.answer(ask.id, "dusra")
    await task
    assert sim.calls == ["+919123456780"]


async def test_classifier_path(world):
    app, sim, client, llm = world
    llm.tool("classifier", "set_volume", action="set", percent=40)
    reply = await app.brain.handle("thodi dheemi awaaz rakh do around forty percent please")
    assert sim.volumes["media"][0] == 6 and reply
    assert llm.requests[0]["model"] == "openai/gpt-oss-20b"


async def test_agent_multistep_task(world):
    app, sim, client, llm = world
    llm.tool("classifier", "phone_task", goal="Like the latest post on Instagram")
    llm.tool("planner", "open_app", name="Instagram")
    llm.tool("planner", "tap", id=4)  # Like button on ig_home
    llm.tool("planner", "done", summary="Liked the latest post", answer="Instagram pe latest post like kar di.")
    llm.text("verifier", '{"done": true, "reason": "Liked shown"}')
    reply = await app.brain.handle("Instagram pe sabse latest post like karo")
    assert sim.liked_post is True
    assert "like kar di" in reply
    roles = [r["role"] for r in llm.requests]
    assert roles.count("planner") == 3 and "verifier" in roles
    assert {r["model"] for r in llm.requests if r["role"] == "planner"} == {"openai/gpt-oss-120b"}


async def test_agent_invalid_element_is_corrected(world):
    app, sim, client, llm = world
    llm.tool("classifier", "phone_task", goal="Turn on dark mode in settings")
    llm.tool("planner", "open_app", name="Settings")
    llm.tool("planner", "tap", id=99)  # invalid -> fed back to the model
    llm.tool("planner", "tap", id=2)  # Display
    llm.tool("planner", "tap", id=3)  # Dark mode switch
    llm.tool("planner", "done", summary="Dark mode on")
    await app.brain.handle("settings mein jaake dark mode on karo")
    assert sim.dark_mode is True
    planner_prompts = [r["body"]["messages"][1]["content"] for r in llm.requests if r["role"] == "planner"]
    assert any("not on the current SCREEN" in p for p in planner_prompts)


async def test_agent_sensitive_tap_requires_confirmation(world):
    app, sim, client, llm = world
    sim.open_chat("Rahul Sharma")
    sim.compose_text = "hello"
    llm.tool("classifier", "phone_task", goal="Press send in the open WhatsApp chat")
    llm.tool("planner", "tap", id=4)  # Send button
    llm.tool("planner", "done", summary="sent")
    task = asyncio.create_task(app.brain.handle("jo likha hai woh bhej do"))
    for _ in range(80):
        if app.gate.pending:
            break
        await asyncio.sleep(0.05)
    assert app.gate.pending, "sensitive tap must ask"
    app.gate.answer(None, "haan")
    await task
    assert sim.whatsapp_sent[-1]["text"] == "hello"


async def test_prompt_injection_on_screen_does_not_expand_tools(world):
    app, sim, client, llm = world
    llm.tool("classifier", "phone_task", goal="Open WhatsApp")
    llm.tool("planner", "run_shell", cmd="rm -rf /")  # hallucinated/injected tool
    llm.tool("planner", "open_app", name="WhatsApp")
    llm.tool("planner", "done", summary="opened")
    await app.brain.handle("whatsapp open karke rakho bas")
    prompts = [r["body"]["messages"][1]["content"] for r in llm.requests if r["role"] == "planner"]
    assert any("Unknown tool 'run_shell'" in p for p in prompts)
    assert sim.screen_name == "wa_chats"


async def test_cancel_and_kill_switch(world):
    app, sim, client, llm = world
    sim.stopped = True
    await client.send_event("stopped", {"reason": "notification"})
    await asyncio.sleep(0.1)
    reply = await app.brain.handle("volume badha do")
    assert "kill switch" in reply.lower()
    assert "Abhi kuch chal nahi raha" in await app.brain.handle("ruk ja")


async def test_offline_reply(world):
    app, sim, client, llm = world
    await client.close()
    await asyncio.sleep(0.2)
    reply = await app.brain.handle("torch on karo")
    assert "connected nahi" in reply


async def test_llm_off_reply(world, monkeypatch):
    app, sim, client, llm = world
    app.cfg.privacy.cloud_llm = False
    reply = await app.brain.handle("kuch interesting batao")
    assert reply  # graceful message, no crash
    assert llm.requests == []


async def test_rate_limit_falls_back_to_next_candidate(world):
    app, sim, client, llm = world
    orig = llm.handler
    calls = {"n": 0}

    def limited(request: httpx.Request) -> httpx.Response:
        if not request.url.path.endswith("/models"):
            body = json.loads(request.content)
            if body["model"] == "openai/gpt-oss-20b" and calls["n"] == 0:
                calls["n"] += 1
                return httpx.Response(429, headers={"retry-after": "30"}, json={"error": {"message": "Rate limit"}})
        return orig(request)

    app.gateway.http = httpx.AsyncClient(transport=httpx.MockTransport(limited))
    app.gateway.cfg.models["classifier"] = ["groq:openai/gpt-oss-20b", "groq:qwen/qwen3-32b"]
    for spec in app.gateway.cfg.models["classifier"]:
        from nixin.llm.gateway import Candidate
        app.gateway.candidates.setdefault(spec, Candidate(spec, *spec.split(":", 1)))
    llm.tool("classifier", "torch", on=True)
    await app.brain.handle("roshni chahiye andhera hai")
    assert sim.torch is True
    assert llm.requests[-1]["model"] == "qwen/qwen3-32b"
