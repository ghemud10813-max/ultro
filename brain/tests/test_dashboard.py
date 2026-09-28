"""Dashboard: token auth, REST, settings, pairing QR and the live websocket."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import websockets

from nixin.app import NixinApp


@pytest.fixture
async def running(cfg, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    cfg.link.host, cfg.link.port = "127.0.0.1", 0
    cfg.dashboard.port = 0
    app = NixinApp(cfg, db_path=":memory:")
    await app.start(with_voice=False, with_dashboard=True)
    port = app._servers[-1].port
    yield app, f"http://127.0.0.1:{port}"
    await app.stop()


async def test_requires_token(running):
    app, base = running
    async with httpx.AsyncClient() as c:
        assert (await c.get(base + "/api/status")).status_code == 401
        assert (await c.get(base + "/")).status_code == 401
        r = await c.get(base + "/", params={"token": app.dashboard_token})
        assert r.status_code == 200 and "Nixin" in r.text
        # cookie set by the first visit authenticates later calls
        assert (await c.get(base + "/api/status")).status_code == 200


async def test_rest_endpoints(running):
    app, base = running
    h = {"x-nixin-token": app.dashboard_token}
    async with httpx.AsyncClient(headers=h) as c:
        st = (await c.get(base + "/api/status")).json()
        assert st["phone"]["connected"] is False
        pair = (await c.post(base + "/api/pair")).json()
        assert pair["uri"].startswith("nixin://pair?d=") and "<svg" in pair["svg"]
        s = (await c.post(base + "/api/settings", json={"assistant.confirm": "always"})).json()
        assert s["assistant.confirm"] == "always" and app.cfg.assistant.confirm == "always"
        assert app.store.get_setting("overrides")["assistant.confirm"] == "always"
        assert (await c.post(base + "/api/settings", json={"assistant.confirm": "yolo"})).status_code == 400
        await c.post(base + "/api/memory/contact", json={"alias": "bhai", "name": "Rohan Sharma"})
        mem = (await c.get(base + "/api/memory")).json()
        assert mem["contacts"][0]["contact_name"] == "Rohan Sharma"
        r = (await c.post(base + "/api/command", json={"text": "time kya hua", "wait": True})).json()
        assert "baje" in r["reply"]
        tasks = (await c.get(base + "/api/tasks")).json()
        assert tasks[0]["text"] == "time kya hua"
        usage = (await c.get(base + "/api/usage")).json()
        assert "planner" in usage["gateway"]["roles"]


async def test_websocket_streams_events(running):
    app, base = running
    url = base.replace("http", "ws") + f"/ws?token={app.dashboard_token}"
    async with websockets.connect(url) as ws:
        hello = json.loads(await ws.recv())
        assert hello["type"] == "hello" and "snapshot" in hello
        await ws.send(json.dumps({"type": "command", "text": "hello"}))
        seen = set()
        for _ in range(20):
            ev = json.loads(await asyncio.wait_for(ws.recv(), 5))
            seen.add(ev["type"])
            if ev["type"] == "say":
                assert "Namaste" in ev["text"] or "Hi" in ev["text"]
                break
        assert "say" in seen


async def test_websocket_rejects_foreign_origin(running):
    app, base = running
    url = base.replace("http", "ws") + f"/ws?token={app.dashboard_token}"
    with pytest.raises((websockets.InvalidStatus, websockets.ConnectionClosed, TimeoutError)):
        async with websockets.connect(url, origin="https://evil.example") as ws:
            await asyncio.wait_for(ws.recv(), 3)


@pytest.fixture
async def dash_world(world, cfg):
    """Dashboard on top of the e2e world (app + simulated phone)."""
    from nixin.core.serve import EmbeddedServer
    from nixin.dashboard.server import Dashboard

    app, sim, client, llm = world
    dash = Dashboard(app)
    srv = EmbeddedServer(dash.app, "127.0.0.1", 0)
    await srv.start()
    yield app, sim, f"http://127.0.0.1:{srv.port}", {"x-nixin-token": dash.token}
    await srv.stop()


async def test_v2_endpoints(dash_world):
    app, sim, base, h = dash_world
    async with httpx.AsyncClient(headers=h, timeout=10) as c:
        r = (await c.get(base + "/api/routines")).json()
        assert any(x["name"] == "Good night" for x in r["routines"]) and "battery_low" in r["events"]
        new = {"name": "Night", "trigger": {"type": "time", "at": "23:00", "days": [1, 2]}, "actions": ["dnd on karo"]}
        saved = (await c.post(base + "/api/routines", json=new)).json()
        assert saved["id"] and app.routines.routines[saved["id"]].trigger.days == [1, 2]
        assert (await c.post(base + "/api/routines", json={"name": "x", "trigger": {"type": "nope"}, "actions": ["a"]})).status_code == 400
        await c.post(base + f"/api/routines/{saved['id']}/run")
        for _ in range(40):
            if sim.dnd:
                break
            await asyncio.sleep(0.05)
        assert sim.dnd is True
        assert (await c.delete(base + f"/api/routines/{saved['id']}")).json()["ok"] is True

        n = (await c.get(base + "/api/notifications")).json()
        assert any(x["title"] == "Mummy" for x in n["items"])
        await c.post(base + "/api/notifications/reply", json={"key": "n2", "text": "haan"})
        assert sim.notif_replies[-1]["text"] == "haan"
        await c.post(base + "/api/settings", json={"notifications.vip": "Mummy, Papa"})
        assert app.cfg.notifications.vip == ["Mummy", "Papa"]

        r = await c.post(base + "/api/files/phone", content=b"hello file", headers={"x-file-name": "notes%20v2.txt",
                                                                                     "content-type": "text/plain"})
        assert r.status_code == 200 and sim.files["notes v2.txt"] == b"hello file"
        await c.post(base + "/api/files/clipboard", content=b"clip!", headers={"content-type": "text/plain"})
        assert sim.clipboard == "clip!"

        ins = (await c.get(base + "/api/insights")).json()
        assert ins["usage"]["totalMs"] > 0 and ins["info"]["model"] == "Simulator"
        loc = (await c.post(base + "/api/phone/locate")).json()
        assert "maps.google.com" in loc["result"]["link"]
        assert (await c.get(base + "/api/skills")).json()["autoReplay"] is True
        assert (await c.get(base + "/api/plugins")).json()["plugins"] == []
        assert (await c.get(base + "/api/inbox")).json()["items"] == []
