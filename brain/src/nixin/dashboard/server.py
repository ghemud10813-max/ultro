"""Local dashboard (http://127.0.0.1:8766/?token=...).

Bound to localhost only and protected by a random per-run token (cookie), so other
machines and random web pages cannot drive your phone through it.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

import segno
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from nixin import __version__
from nixin.app import RUNTIME_SETTINGS
from nixin.features.routines import EVENTS, Routine
from nixin.link.protocol import PhoneError

if TYPE_CHECKING:
    from nixin.app import NixinApp

STATIC = Path(__file__).parent / "static"
COOKIE = "nixin_token"
MAX_UPLOAD = 200 * 1024 * 1024


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

        # ------------------------------------------------------------ v2: automations
        @a.get("/api/routines")
        async def routines(request: Request):
            self._guard(request)
            return {"routines": [r.model_dump() for r in self.nx.routines.list()], "events": list(EVENTS)}

        @a.post("/api/routines")
        async def save_routine(request: Request):
            self._guard(request)
            b = await request.json()
            try:
                r = Routine.model_validate(b)
            except Exception as e:  # noqa: BLE001
                raise HTTPException(400, f"Invalid routine: {e}") from e
            if not r.actions:
                raise HTTPException(400, "A routine needs at least one action")
            return self.nx.routines.save(r).model_dump()

        @a.delete("/api/routines/{rid}")
        async def delete_routine(request: Request, rid: str):
            self._guard(request)
            return {"ok": self.nx.routines.delete(rid)}

        @a.post("/api/routines/{rid}/run")
        async def run_routine(request: Request, rid: str):
            self._guard(request)
            r = self.nx.routines.routines.get(rid)
            if r is None:
                raise HTTPException(404)
            asyncio.create_task(self.nx.routines.run(r, {}, "dashboard"))
            return {"ok": True}

        @a.get("/api/skills")
        async def skills(request: Request):
            self._guard(request)
            sk = self.nx.skills
            return {"skills": [asdict(s) for s in sk.list()], "autoReplay": sk.auto_replay, "recording": sk.recording}

        @a.post("/api/skills/auto_replay")
        async def skills_auto(request: Request):
            self._guard(request)
            on = bool((await request.json()).get("on"))
            self.nx.skills.auto_replay = on
            self.nx.store.set_setting("skills_auto_replay", on)
            return {"autoReplay": on}

        @a.delete("/api/skills/{sid}")
        async def delete_skill(request: Request, sid: str):
            self._guard(request)
            return {"ok": self.nx.skills.delete(sid)}

        @a.post("/api/skills/{sid}/run")
        async def run_skill(request: Request, sid: str):
            self._guard(request)
            s = self.nx.skills.skills.get(sid)
            if s is None:
                raise HTTPException(404)
            asyncio.create_task(self.nx.brain.handle(f"{s.name} chalao", source="dashboard") if s.kind == "taught"
                                else self.nx.brain.handle(s.goal or s.name, source="dashboard"))
            return {"ok": True}

        @a.get("/api/plugins")
        async def plugins(request: Request):
            self._guard(request)
            p = self.nx.plugins
            return {"plugins": p.describe(), "errors": p.errors, "dirs": [str(d) for d in p.dirs]}

        @a.post("/api/plugins/reload")
        async def reload_plugins(request: Request):
            self._guard(request)
            self.nx.plugins.load()
            return {"plugins": self.nx.plugins.describe(), "errors": self.nx.plugins.errors}

        # ------------------------------------------------------------ v2: notifications
        @a.get("/api/notifications")
        async def notifications(request: Request):
            self._guard(request)
            nc = self.nx.notifications
            items = sorted(nc.live.values(), key=lambda n: -(n.get("received") or 0))
            if self.nx.phone.connected:
                try:
                    res = await self.nx.phone.call("notif.list", {"limit": 20}, origin="dashboard")
                    seen = {n.get("key") for n in items}
                    items += [n for n in res.get("notifications") or [] if n.get("key") not in seen]
                except PhoneError:
                    pass
            cfg = self.nx.cfg.notifications
            return {"items": items[:60], "settings": {"announce": cfg.announce, "vip": cfg.vip,
                                                       "announce_apps": cfg.announce_apps, "toast_on_pc": cfg.toast_on_pc}}

        @a.post("/api/notifications/{action}")
        async def notif_action(request: Request, action: str):
            self._guard(request)
            b = await request.json()
            try:
                if action == "reply":
                    text = str(b.get("text") or "").strip()
                    if not b.get("key") or not text:
                        raise HTTPException(400, "key and text required")
                    # typed on the dashboard and sent with an explicit click = confirmed by the user
                    res = await self.nx.phone.call("notif.reply", {"key": b["key"], "text": text[:2000]}, origin="dashboard",
                                                   confirmed=True)
                    self.nx.notifications.live.pop(b["key"], None)
                elif action == "dismiss":
                    res = await self.nx.phone.call("notif.dismiss", {"all": True} if b.get("all") else {"key": b["key"]},
                                                   origin="dashboard")
                    if b.get("all"):
                        self.nx.notifications.live.clear()
                    else:
                        self.nx.notifications.live.pop(b.get("key"), None)
                elif action == "open":
                    res = await self.nx.phone.call("notif.open", {"key": b["key"]}, origin="dashboard")
                else:
                    raise HTTPException(404)
            except PhoneError as e:
                return JSONResponse({"error": e.to_dict()}, status_code=409)
            return {"ok": True, "result": res}

        # ------------------------------------------------------------ v2: files / inbox
        @a.get("/api/inbox")
        async def inbox(request: Request):
            self._guard(request)
            return {"items": self.nx.bridge.list_items(60), "folder": str(self.nx.bridge.inbox)}

        @a.get("/api/inbox/{iid}/file")
        async def inbox_file(request: Request, iid: str):
            self._guard(request)
            item = next((i for i in self.nx.bridge.existing_files() if i.id == iid), None)
            if item is None:
                raise HTTPException(404)
            return FileResponse(item.path, filename=item.name, media_type=item.mime or "application/octet-stream")

        @a.post("/api/files/{target}")
        async def push_file(request: Request, target: str):
            """Raw body upload (no multipart dependency): header x-file-name, content-type."""
            self._guard(request)
            if int(request.headers.get("content-length") or 0) > MAX_UPLOAD:
                raise HTTPException(413, "File too large (max 200 MB)")
            data = await request.body()
            if not data:
                raise HTTPException(400, "empty file")
            if len(data) > MAX_UPLOAD:
                raise HTTPException(413, "File too large (max 200 MB)")
            name = unquote(request.headers.get("x-file-name") or "file")
            mime = request.headers.get("content-type") or "application/octet-stream"
            try:
                if target == "phone":
                    res = await self.nx.bridge.push_bytes(data, name, mime)
                elif target == "wallpaper":
                    res = await self.nx.bridge.set_wallpaper(data, request.query_params.get("where") or "both")
                elif target == "clipboard":
                    res = await self.nx.phone.call("clipboard.set", {"text": data.decode("utf-8", "replace")[:100000]},
                                                   origin="dashboard")
                else:
                    raise HTTPException(404)
            except PhoneError as e:
                return JSONResponse({"error": e.to_dict()}, status_code=409)
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
            return {"ok": True, "result": res}

        # ------------------------------------------------------------ v2: phone insights / extras, PC
        @a.get("/api/insights")
        async def insights(request: Request, period: str = "today"):
            self._guard(request)
            out: dict[str, Any] = {"connected": self.nx.phone.connected}
            if not self.nx.phone.connected:
                return out
            for key, method, params in (("usage", "usage.stats", {"period": period if period in ("today", "yesterday", "week") else "today",
                                                                   "limit": 12}),
                                        ("info", "device.info", {}), ("playing", "media.now_playing", {})):
                try:
                    out[key] = await self.nx.phone.call(method, params, origin="dashboard")
                except PhoneError as e:
                    out[key] = {"error": e.to_dict()}
            return out

        @a.post("/api/phone/{action}")
        async def phone_action(request: Request, action: str):
            self._guard(request)
            try:
                if action == "ring":
                    res = await self.nx.phone.call("device.ring", {"seconds": 30}, origin="dashboard")
                elif action == "stop_ring":
                    res = await self.nx.phone.call("device.ring", {"stop": True}, origin="dashboard")
                elif action == "locate":
                    res = await self.nx.phone.call("device.location", {"timeoutMs": 12000}, origin="dashboard", timeout=16)
                    if res.get("lat") is not None:
                        res["link"] = f"https://maps.google.com/?q={res['lat']:.6f},{res['lon']:.6f}"
                elif action == "teach_stop":
                    res = {"reply": await self.nx.brain.handle("recording save karo", source="dashboard")}
                else:
                    raise HTTPException(404)
            except PhoneError as e:
                return JSONResponse({"error": e.to_dict()}, status_code=409)
            return {"ok": True, "result": res}

        @a.get("/api/pc")
        async def pc_status(request: Request):
            self._guard(request)
            st = await self.nx.pc.pc.status()
            return {"cpu": st.cpu, "ram": st.ram, "battery": st.battery, "charging": st.charging, "host": st.host, "os": st.os}

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
            "recording": nx.skills.recording,
            "counts": {"routines": len(nx.routines.routines), "skills": len(nx.skills.skills),
                       "inbox": len(nx.bridge.items), "notifications": len(nx.notifications.live),
                       "plugins": len(nx.plugins.commands)},
        }
