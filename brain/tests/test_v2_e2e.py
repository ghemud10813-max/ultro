"""End-to-end tests for Nixin 2.0 features: NixinApp + simulated phone (real TLS link) + fake PC/LLM/weather."""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from nixin.features.pc_control import PcStatus
from nixin.sim.phone_sim import SimPhone

ROOT = Path(__file__).resolve().parents[2]


class FakePc:
    def __init__(self) -> None:
        self.calls: list = []
        self.clip = "text copied on the PC"

    async def lock(self):
        self.calls.append("lock")
        return "locked"

    async def sleep(self):
        self.calls.append("sleep")
        return "sleeping"

    async def shutdown(self, restart=False, delay_seconds=60):
        self.calls.append(("shutdown", restart))
        return "restart" if restart else "shutdown"

    async def cancel_shutdown(self):
        self.calls.append("cancel_shutdown")
        return "cancelled"

    async def volume(self, action, percent=None, steps=3):
        self.calls.append(("volume", action, percent))
        return "40%"

    async def media(self, action):
        self.calls.append(("media", action))
        return action

    async def open(self, target):
        self.calls.append(("open", target))
        return target

    async def search(self, query):
        self.calls.append(("search", query))
        return query

    async def screenshot(self, max_width=1920, quality=80):
        return b"\xff\xd8\xff\xe0fake-jpeg" * 10

    async def clipboard_get(self):
        return self.clip

    async def clipboard_set(self, text):
        self.clip = text

    async def type_text(self, text):
        self.calls.append(("type", text))

    async def status(self):
        return PcStatus(12.0, 41.0, 80, True, "Test-PC", "Linux")

    async def notify(self, title, text):
        self.calls.append(("notify", title, text))


def weather_client() -> httpx.AsyncClient:
    def handler(req: httpx.Request) -> httpx.Response:
        if "geocoding" in req.url.host:
            return httpx.Response(200, json={"results": [{"name": "Delhi", "latitude": 28.61, "longitude": 77.21}]})
        return httpx.Response(200, json={
            "current": {"temperature_2m": 31.4, "apparent_temperature": 35.2, "weather_code": 2},
            "daily": {"weather_code": [2, 63], "temperature_2m_max": [34, 30], "temperature_2m_min": [26, 24],
                      "precipitation_probability_max": [10, 80]}})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
async def v2(world):
    app, sim, client, llm = world
    app.pc.pc = FakePc()
    app.weather.weather.http = weather_client()
    app.skills.pause = app.skills.open_pause = 0.01
    yield app, sim, client, llm


async def next_msg(client, t: str, pred=lambda m: True, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while True:
        msg = await asyncio.wait_for(client.inbox.get(), max(0.05, deadline - time.time()))
        if msg.get("t") == t and pred(msg):
            return msg


async def until(cond, timeout: float = 5.0) -> None:
    for _ in range(int(timeout / 0.05)):
        if cond():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met in time")


# ------------------------------------------------------------------ protocol parity
def test_simulator_implements_every_method():
    methods = json.loads((ROOT / "shared" / "protocol" / "methods.json").read_text())["methods"]
    src = inspect.getsource(SimPhone.handle)
    missing = [m for m in methods if f'"{m}"' not in src]
    assert missing == []


# ------------------------------------------------------------------ PC control
async def test_pc_control_from_the_phone(v2):
    app, sim, client, llm = v2
    reply = await app.brain.handle("PC lock karo", source="phone_text")
    assert app.pc.pc.calls == ["lock"] and "lock" in reply.lower()
    await app.brain.handle("laptop ka volume 40 percent kar do", source="phone_text")
    assert ("volume", "set", 40) in app.pc.pc.calls
    reply = await app.brain.handle("PC ka screenshot bhejo", source="phone_text")
    assert any(n.startswith("PC-screenshot") for n in sim.files) and "phone" in reply.lower()
    await app.brain.handle("PC ka clipboard phone pe bhejo")
    assert sim.clipboard == "text copied on the PC"
    sim.clipboard = "copied on the phone"
    await app.brain.handle("phone ka clipboard pc pe bhejo")
    assert app.pc.pc.clip == "copied on the phone"
    assert llm.requests == []


async def test_pc_shutdown_always_confirms(v2):
    app, sim, client, llm = v2
    task = asyncio.create_task(app.brain.handle("PC band kar do"))
    await until(lambda: app.gate.pending)
    app.gate.answer(None, "haan")
    reply = await task
    assert ("shutdown", False) in app.pc.pc.calls and "shutdown cancel" in reply
    await app.brain.handle("shutdown cancel karo")
    assert "cancel_shutdown" in app.pc.pc.calls


# ------------------------------------------------------------------ weather & briefing
async def test_weather_for_a_city_and_phone_location(v2):
    app, sim, client, llm = v2
    reply = await app.brain.handle("Delhi ka mausam kaisa hai")
    assert "Delhi" in reply and "31" in reply
    reply = await app.brain.handle("kal barish hogi?")
    assert "80%" in reply and "chhata" in reply  # phone location, tomorrow's rain chance
    assert "device.location" in sim.history


async def test_briefing(v2):
    app, sim, client, llm = v2
    app.cfg.privacy.cloud_llm = False  # grouped notification summary (no LLM)
    reply = await app.brain.handle("briefing do")
    assert "battery 78%" in reply.lower() and "31" in reply and "Instagram" in reply and "3 ghante" in reply


# ------------------------------------------------------------------ routines
async def test_voice_created_time_routine_runs(v2):
    app, sim, client, llm = v2
    reply = await app.brain.handle("har raat 11 baje phone silent kar dena")
    assert "Routine bana di" in reply
    r = next(r for r in app.routines.list() if r.trigger.type == "time" and r.trigger.at == "23:00")
    assert r in app.routines.due_by_clock(datetime(2026, 9, 28, 23, 0))
    await app.routines.run(r, {}, "time")
    assert sim.ringer == "silent"
    msg = await next_msg(client, "say", lambda m: "⏰" in m["text"])
    assert r.name in msg["text"]


async def test_event_routine_announces_low_battery(v2):
    app, sim, client, llm = v2
    await app.brain.handle("jab battery 25% se kam ho to bata dena")
    await client.send_event("battery", {"level": 24, "charging": False})
    msg = await next_msg(client, "say", lambda m: "24%" in m["text"] and m.get("speak"))
    assert "charger" in msg["text"]


async def test_reminder_fires_with_notification(v2):
    app, sim, client, llm = v2
    reply = await app.brain.handle("10 minute baad yaad dilana ki chai bana lu")
    assert "chai bana lu" in reply
    r = next(r for r in app.routines.list() if r.trigger.type == "once")
    r.trigger.when = time.time() - 1
    assert r in app.routines.due_by_clock(datetime.now())
    await app.routines.run(r, {}, "time")
    assert sim.nixin_notifs[-1]["text"] == "chai bana lu"
    assert app.routines.find(r.name) is None  # one-shot routines delete themselves


async def test_scene_phrase_runs_builtin_routine(v2):
    app, sim, client, llm = v2
    reply = await app.brain.handle("good night")
    assert sim.dnd is True and sim.brightness == 15 and "Good night" in reply
    assert llm.requests == []


async def test_routine_external_action_still_confirms(v2):
    app, sim, client, llm = v2
    await app.brain.handle("har roz 9 baje Mummy ko bolo good morning")
    r = next(r for r in app.routines.list() if r.trigger.type == "time" and r.trigger.at == "09:00")
    run = asyncio.create_task(app.routines.run(r, {}, "time"))
    await until(lambda: app.gate.pending)
    app.gate.answer(None, "yes")
    await run
    assert sim.whatsapp_sent[-1]["text"] == "good morning" and sim.whatsapp_sent[-1]["name"] == "Mummy"


async def test_scenes_sent_to_phone_on_connect(v2):
    app, sim, client, llm = v2
    await app._on_phone_connected()
    msg = await next_msg(client, "scenes")
    assert any(i["label"] == "Good night" for i in msg["items"])


# ------------------------------------------------------------------ teach mode / skills
async def test_teach_mode_records_and_replays(v2):
    app, sim, client, llm = v2
    reply = await app.brain.handle("sikho: mummy chat")
    assert sim.recording == "mummy chat" and "save karo" in reply
    sim.user_open("com.whatsapp")
    sim.user_tap("Mummy")
    sim.user_type("hello")
    reply = await app.brain.handle("save karo")
    assert "seekh liya (3 steps)" in reply
    sim.go("home")
    sim.compose_text = ""
    reply = await app.brain.handle("mummy chat chalao")
    assert sim.chat_with == "Mummy" and sim.compose_text == "hello" and "ho gaya" in reply
    sim.go("home")
    await app.brain.handle("mummy chat: kaise ho")
    assert sim.compose_text == "kaise ho"
    assert llm.requests == []


async def test_agent_route_is_learned_and_replayed(v2):
    app, sim, client, llm = v2
    llm.tool("classifier", "phone_task", goal="Turn on dark mode in settings")
    llm.tool("planner", "open_app", name="Settings")
    llm.tool("planner", "tap", id=2)  # Display
    llm.tool("planner", "tap", id=3)  # Dark mode switch
    llm.tool("planner", "done", summary="Dark mode is on")
    await app.brain.handle("settings mein jaake dark mode on karo")
    assert sim.dark_mode is True
    learned = [s for s in app.skills.list() if s.kind == "auto"]
    assert len(learned) == 1 and [s["a"] for s in learned[0].steps] == ["open", "tap", "tap"]
    sim.dark_mode = False
    sim.go("home")
    planner_calls = sum(1 for r in llm.requests if r["role"] == "planner")
    llm.tool("classifier", "phone_task", goal="Turn on dark mode in settings")
    await app.brain.handle("settings mein jaake dark mode on karo")
    assert sim.dark_mode is True
    assert sum(1 for r in llm.requests if r["role"] == "planner") == planner_calls  # replayed, no planner


# ------------------------------------------------------------------ notifications
async def test_vip_notification_is_announced_and_replied(v2):
    app, sim, client, llm = v2
    app.cfg.notifications.vip = ["Mummy"]
    await client.send_event("notification", {"key": "n9", "package": "com.whatsapp", "app": "WhatsApp", "title": "Mummy",
                                             "text": "Kab aa rahe ho?", "canReply": True})
    msg = await next_msg(client, "say", lambda m: "Kab aa rahe ho" in m["text"])
    assert msg["speak"] is True
    reply = await app.brain.handle("Mummy ko reply karo: bas 10 minute")
    assert sim.notif_replies[-1] == {"key": "n2", "title": "Mummy", "app": "WhatsApp", "text": "bas 10 minute"}
    assert "bhej diya" in reply


async def test_reply_falls_back_to_message_and_clear(v2):
    app, sim, client, llm = v2
    await app.brain.handle("Priya ko reply karo: ok")
    assert sim.whatsapp_sent[-1]["name"] == "Priya"  # no notification from Priya -> normal WhatsApp message
    await app.brain.handle("instagram ki notifications clear karo")
    assert all(n["package"] != "com.instagram.android" for n in sim.notifications)
    await app.brain.handle("notifications clear karo")
    assert sim.notifications == []


async def test_notification_summary_with_llm(v2):
    app, sim, client, llm = v2
    llm.text("verifier", "Mummy ne WhatsApp pe pucha khana khaya ki nahi, aur priya_k ne photo like ki.")
    reply = await app.brain.handle("mere messages summarize karo")
    assert reply.startswith("Mummy ne WhatsApp")


# ------------------------------------------------------------------ bridge
async def test_share_and_files_from_phone(v2, tmp_path):
    app, sim, client, llm = v2
    await client.share("https://example.com/article")
    await until(lambda: app.bridge.items and app.bridge.items[0].kind == "url")
    tid = await client.send_file("photo.jpg", b"\x89PNG-ish" * 50000, "image/jpeg", chunk=100_000)
    ack = await next_msg(client, "file_ack", lambda m: m["transferId"] == tid)
    assert ack["ok"] is True and ack["name"] == "photo.jpg"
    saved = Path(app.bridge.items[0].path)
    assert await asyncio.to_thread(saved.read_bytes) == b"\x89PNG-ish" * 50000 and saved.parent == app.bridge.inbox
    await app.brain.handle("ye photo wallpaper laga do")
    assert sim.wallpaper == b"\x89PNG-ish" * 50000
    reply = await app.brain.handle("inbox dikhao")
    assert "photo.jpg" in reply and "example.com" in reply


# ------------------------------------------------------------------ deeper phone control
async def test_phone_extras(v2):
    app, sim, client, llm = v2
    await app.brain.handle("mera phone kahan hai")
    assert sim.ringing is True
    await app.brain.handle("ringing band karo")
    assert sim.ringing is False
    reply = await app.brain.handle("phone ki location batao")
    assert "maps.google.com/?q=28.613900,77.209000" in reply
    reply = await app.brain.handle("aaj maine phone kitna chalaya")
    assert "3 ghante 12 minute" in reply and "Instagram" in reply
    reply = await app.brain.handle("storage kitna bacha hai")
    assert "42.0 GB" in reply
    await app.brain.handle("auto rotate band karo")
    assert sim.system["auto_rotate"] is False
    await app.brain.handle("screen timeout 2 minute kar do")
    assert sim.system["screen_timeout"] == 120
    sim.call_state = "ringing"
    await app.brain.handle("call utha lo")
    assert sim.call_state == "active"
    await app.brain.handle("speaker on karo")
    assert sim.speaker is True
    assert llm.requests == []


async def test_screen_read_without_llm(v2):
    app, sim, client, llm = v2
    app.cfg.privacy.cloud_llm = False
    sim.open_package("com.instagram.android")
    reply = await app.brain.handle("screen pe kya hai")
    assert "Instagram" in reply and "priya_k" in reply


# ------------------------------------------------------------------ smarter conversation
async def test_follow_up_pronouns_and_same_message(v2):
    app, sim, client, llm = v2
    await app.brain.handle("Priya ko bolo kal milte hain")
    await app.brain.handle("usko call bhi karo")
    assert sim.calls[-1] == "+918888822222"
    await app.brain.handle("wahi message Mummy ko bhi bhejo")
    assert sim.whatsapp_sent[-1] == {**sim.whatsapp_sent[-1], "name": "Mummy", "text": "kal milte hain"}


# ------------------------------------------------------------------ plugins
async def test_plugins(v2):
    app, sim, client, llm = v2
    folder = app.cfg.data_path / "plugins"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "fun.py").write_text(
        "from nixin.features.plugins import command\n\n"
        "@command(r'^sikka uchalo$', name='coin')\n"
        "async def coin(ctx):\n    return 'Heads!'\n\n"
        "@command(r'^party mode$', name='party', needs_phone=True)\n"
        "async def party(ctx):\n    await ctx.run('torch on karo')\n    return 'Party shuru!'\n")
    (folder / "broken.py").write_text("raise RuntimeError('nope')\n")
    app.plugins.load()
    assert {c.name for c in app.plugins.commands} == {"coin", "party"}
    assert any("broken.py" in k for k in app.plugins.errors)
    assert await app.brain.handle("sikka uchalo") == "Heads!"
    assert await app.brain.handle("party mode") == "Party shuru!"
    assert sim.torch is True


async def test_example_plugin_file(v2):
    import shutil

    app, sim, client, llm = v2
    folder = app.cfg.data_path / "plugins"
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "brain" / "examples" / "plugins" / "fun_and_tools.py", folder / "fun_and_tools.py")
    app.plugins.load()
    assert {"coin", "dice", "party", "notepad"} <= {c.name for c in app.plugins.commands}
    assert (await app.brain.handle("sikka uchalo")).startswith(("Heads", "Tails"))
    assert (await app.brain.handle("roll a dice"))[0] in "123456"
    await app.brain.handle("pc pe notepad kholo aur likho milk and eggs")
    assert ("open", "notepad") in app.pc.pc.calls and ("type", "milk and eggs") in app.pc.pc.calls
