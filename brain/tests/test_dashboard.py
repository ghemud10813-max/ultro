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
    with pytest.raises(Exception):
        async with websockets.connect(url, origin="https://evil.example") as ws:
            await asyncio.wait_for(ws.recv(), 3)
