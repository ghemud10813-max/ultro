"""Local dashboard (http://127.0.0.1:8766/?token=...).

Bound to localhost only and protected by a random per-run token (cookie), so other
machines and random web pages cannot drive your phone through it.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import segno
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from nixin import __version__
from nixin.app import RUNTIME_SETTINGS
from nixin.link.protocol import PhoneError

if TYPE_CHECKING:
    from nixin.app import NixinApp

STATIC = Path(__file__).parent / "static"
COOKIE = "nixin_token"


class Dashboard:
    def __init__(self, app: NixinApp) -> None:
        self.nx = app
        self.token = secrets.token_urlsafe(18)
        self.mirror_clients = 0
        self._mirror_task: asyncio.Task | None = None
        self.app = FastAPI(title="Nixin Dashboard", docs_url=None, redoc_url=None, openapi_url=None)
        self._routes()

    # ------------------------------------------------------------------ auth
    def _authed(self, request: Request | WebSocket) -> bool:
        tok = request.cookies.get(COOKIE) or request.query_params.get("token") or request.headers.get("x-nixin-token")
        return bool(tok) and secrets.compare_digest(tok, self.token)

    def _guard(self, request: Request) -> None:
        if not self._authed(request):
            raise HTTPException(401, "Missing or wrong dashboard token — open the link printed in the console.")

    # ------------------------------------------------------------------ routes
    def _routes(self) -> None:
        a = self.app

        @a.get("/")
        async def index(request: Request):
            if not self._authed(request):
                return HTMLResponse("<h3 style='font-family:sans-serif'>Nixin: open the dashboard link printed in the "
                                    "console (it contains the access token).</h3>", status_code=401)
            resp = FileResponse(STATIC / "index.html")
            if request.query_params.get("token"):
                resp.set_cookie(COOKIE, self.token, httponly=True, samesite="strict")
            return resp

        @a.get("/static/{name}")
        async def static(name: str):
            p = (STATIC / name).resolve()
            if STATIC.resolve() not in p.parents or not p.exists():
                raise HTTPException(404)
            return FileResponse(p)

        @a.get("/api/status")
        async def status(request: Request):
            self._guard(request)
            return self.snapshot()

        @a.get("/api/tasks")
        async def tasks(request: Request, limit: int = 50):
            self._guard(request)
            return self.nx.store.list_tasks(limit)

        @a.get("/api/tasks/{task_id}")
        async def task(request: Request, task_id: str):
            self._guard(request)
            t = self.nx.store.get_task(task_id)
            if not t:
                raise HTTPException(404)
            return t

        @a.get("/api/audit")
        async def audit(request: Request, limit: int = 100):
            self._guard(request)
            return self.nx.store.list_audit(limit)

        @a.get("/api/usage")
        async def usage(request: Request):
            self._guard(request)
            return {"today": self.nx.store.usage_today(), "days": self.nx.store.usage_days(7),
                    "gateway": self.nx.gateway.status()}

        @a.post("/api/models/probe")
        async def probe(request: Request):
            self._guard(request)
            return {"report": await self.nx.gateway.probe(), "gateway": self.nx.gateway.status()}

        @a.get("/api/settings")
        async def get_settings(request: Request):
            self._guard(request)
            return self.settings()

        @a.post("/api/settings")
        async def set_settings(request: Request):
            self._guard(request)
            body = await request.json()
            for k, v in body.items():
                try:
                    self.nx.set_setting(k, v)
                except Exception as e:  # noqa: BLE001
                    raise HTTPException(400, f"{k}: {e}") from e
            return self.settings()

        @a.get("/api/memory")
        async def memory(request: Request):
            self._guard(request)
            s = self.nx.store
            return {"contacts": s.list_contact_aliases(), "apps": s.list_app_aliases(), "facts": s.list_facts(100)}

        @a.post("/api/memory/contact")
        async def add_contact(request: Request):
            self._guard(request)
            b = await request.json()
            if not b.get("alias") or not b.get("name"):
                raise HTTPException(400, "alias and name required")
            self.nx.store.set_contact_alias(b["alias"], b["name"], b.get("number") or None)
            return {"ok": True}

        @a.delete("/api/memory/contact/{alias}")
        async def del_contact(request: Request, alias: str):
            self._guard(request)
            return {"ok": self.nx.store.delete_contact_alias(alias)}

        @a.post("/api/memory/app")
        async def add_app(request: Request):
            self._guard(request)
            b = await request.json()
            if not b.get("alias") or not b.get("package"):
                raise HTTPException(400, "alias and package required")
            self.nx.store.set_app_alias(b["alias"], b["package"], b.get("label"))
            return {"ok": True}

        @a.delete("/api/memory/app/{alias}")
        async def del_app(request: Request, alias: str):
            self._guard(request)
            return {"ok": self.nx.store.delete_app_alias(alias)}

        @a.post("/api/memory/fact")
        async def add_fact(request: Request):
            self._guard(request)
            b = await request.json()
            if not (b.get("text") or "").strip():
                raise HTTPException(400, "text required")
            return {"id": self.nx.store.add_fact(b["text"])}

        @a.delete("/api/memory/fact/{fact_id}")
        async def del_fact(request: Request, fact_id: int):
            self._guard(request)
            return {"ok": self.nx.store.delete_fact(fact_id)}

        @a.post("/api/pair")
        async def pair(request: Request):
            self._guard(request)
            offer = self.nx.new_pairing()
            qr = segno.make(offer.uri, error="m")
            return {"uri": offer.uri, "expires": offer.expires_at, "endpoints": offer.payload["endpoints"],
                    "fingerprint": self.nx.identity.fingerprint, "svg": qr.svg_inline(scale=5, dark="#0b0d12", light="#ffffff")}

        @a.get("/api/devices")
        async def devices(request: Request):
            self._guard(request)
            return self.nx.store.list_devices()

        @a.delete("/api/devices/{device_id}")
        async def unpair(request: Request, device_id: str):
            self._guard(request)
            ok = self.nx.store.revoke_device(device_id)
            s = self.nx.phone.session
            if ok and s and s.device_id == device_id:
                await s.transport.close(4006, "unpaired")
            return {"ok": ok}

        @a.post("/api/command")
        async def command(request: Request):
            self._guard(request)
            b = await request.json()
            text = (b.get("text") or "").strip()
            if not text:
                raise HTTPException(400, "text required")
            if b.get("wait"):
                return {"reply": await self.nx.brain.handle(text, source="api")}
            asyncio.create_task(self.nx.brain.handle(text, source="dashboard"))
            return {"accepted": True}

        @a.get("/api/screenshot")
        async def screenshot(request: Request):
            self._guard(request)
            try:
                cap = await self.nx.phone.call("screen.capture", {"maxWidth": 720, "quality": 70}, origin="dashboard")
            except PhoneError as e:
                return JSONResponse({"error": e.to_dict()}, status_code=409)
            import base64

            return Response(base64.b64decode(cap["data"]), media_type="image/jpeg")

        @a.websocket("/ws")
        async def ws(websocket: WebSocket):
            origin = websocket.headers.get("origin", "")
            if not self._authed(websocket) or (origin and not origin.startswith(("http://127.0.0.1", "http://localhost"))):
                await websocket.close(code=4401)
                return
            await websocket.accept()
            q = self.nx.bus.subscribe()
            mirror = False
            await websocket.send_text(json.dumps({"type": "hello", "snapshot": self.snapshot(),
                                                  "events": self.nx.bus.recent(150)}, default=str))

            async def pump():
                while True:
                    ev = await q.get()
                    if ev["type"] == "frame" and not mirror:
                        continue
                    await websocket.send_text(json.dumps(ev, default=str))

            pump_task = asyncio.create_task(pump())
            try:
                while True:
                    msg = json.loads(await websocket.receive_text())
                    t = msg.get("type")
                    if t == "mirror":
                        want = bool(msg.get("on"))
                        if want != mirror:
                            mirror = want
                            self.mirror_clients += 1 if want else -1
                            self._ensure_mirror()
                    else:
                        await self._client_msg(msg)
            except (WebSocketDisconnect, RuntimeError, json.JSONDecodeError):
                pass
            finally:
                pump_task.cancel()
                self.nx.bus.unsubscribe(q)
                if mirror:
                    self.mirror_clients -= 1

    # ------------------------------------------------------------------ helpers
    async def _client_msg(self, msg: dict) -> None:
        t = msg.get("type")
        nx = self.nx
        try:
            if t == "command" and (msg.get("text") or "").strip():
                asyncio.create_task(nx.brain.handle(msg["text"], source="dashboard"))
            elif t == "answer":
                nx.gate.answer(msg.get("id"), str(msg.get("value", "")))
            elif t == "cancel":
                nx.brain.cancel_current()
            elif t == "tap":
                await nx.phone.call("ui.tap", {"x": int(msg["x"]), "y": int(msg["y"])}, origin="dashboard", confirmed=True)
            elif t == "swipe":
                await nx.phone.call("ui.swipe", {k: int(msg[k]) for k in ("x1", "y1", "x2", "y2")} | {"durationMs": 250},
                                    origin="dashboard")
            elif t == "global":
                await nx.phone.call("device.global", {"action": msg["action"]}, origin="dashboard")
            elif t == "type":
                await nx.phone.call("ui.type", {"text": str(msg.get("text", "")), "clear": False,
                                                "submit": bool(msg.get("submit"))}, origin="dashboard")
            elif t == "ptt" and nx.voice:
                asyncio.create_task(nx.voice.push_to_talk("voice"))
        except PhoneError as e:
            nx.bus.emit("log", level="warning", msg=f"Dashboard action failed: {e.code} {e.message}")
        except (KeyError, ValueError, TypeError) as e:
            nx.bus.emit("log", level="warning", msg=f"Bad dashboard message: {e}")

    def _ensure_mirror(self) -> None:
        if self.mirror_clients > 0 and (self._mirror_task is None or self._mirror_task.done()):
            self._mirror_task = asyncio.create_task(self._mirror_loop())

    async def _mirror_loop(self) -> None:
        interval = 1.0 / max(0.2, min(3.0, self.nx.cfg.dashboard.mirror_fps))
        while self.mirror_clients > 0:
            t0 = time.time()
            if self.nx.phone.connected and not self.nx.phone.stopped:
                try:
                    cap = await self.nx.phone.call("screen.capture", {"maxWidth": 540, "quality": 55}, origin="dashboard",
                                                   timeout=8)
                    self.nx.bus.emit("frame", data=cap["data"], width=cap.get("width"), height=cap.get("height"),
                                     screenWidth=cap.get("screenWidth"), screenHeight=cap.get("screenHeight"))
                except PhoneError as e:
                    self.nx.bus.emit("frame_error", code=e.code, message=e.message)
                    await asyncio.sleep(3)
            await asyncio.sleep(max(0.05, interval - (time.time() - t0)))

    def settings(self) -> dict[str, Any]:
        out = {}
        for key in RUNTIME_SETTINGS:
            section, name = key.split(".", 1)
            out[key] = getattr(getattr(self.nx.cfg, section), name)
        return out

    def snapshot(self) -> dict:
        nx = self.nx
        pend = nx.gate.current
        return {
            "version": __version__,
            "pc": {"name": nx.identity.pc_name, "fingerprint": nx.identity.fingerprint, "endpoints": nx.endpoints()},
            "phone": nx.phone.describe(),
            "voice": bool(nx.voice),
            "busy": nx.brain.current is not None,
            "ask": {"id": pend.id, "kind": pend.kind, "text": pend.text, "options": pend.options} if pend else None,
            "settings": self.settings(),
            "gateway": nx.gateway.status(),
            "adb": nx.adb.enabled,
        }
