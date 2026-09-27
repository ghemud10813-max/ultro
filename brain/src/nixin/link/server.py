"""WSS endpoint the phone connects to (``wss://<pc>:8765/link``).

Handshake:  PC hello(nonce) -> phone pair|auth(signature) -> PC welcome | denied
After that both sides exchange req/res, event, cmd, say, ask/answer, cancel, ping/pong.
"""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from nixin import PROTOCOL_VERSION, __version__
from nixin.core.events import EventBus
from nixin.core.store import Store
from nixin.link.phone import PhoneLink, PhoneSession
from nixin.security.certs import PcIdentity
from nixin.security.pairing import (
    PairingManager,
    auth_message,
    new_nonce,
    pair_message,
    verify_signature,
)

MAX_FRAME = 4 * 1024 * 1024
CLOSE_AUTH_FAILED = 4001
CLOSE_TIMEOUT = 4005


class _WsTransport:
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws

    async def send_text(self, data: str) -> None:
        await self.ws.send_text(data)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        await self.ws.close(code=code, reason=reason)


class LinkServer:
    def __init__(
        self,
        identity: PcIdentity,
        pairing: PairingManager,
        phone: PhoneLink,
        store: Store,
        bus: EventBus,
        heartbeat_seconds: int = 15,
        extra_blocklist: list[str] | None = None,
    ) -> None:
        self.identity = identity
        self.pairing = pairing
        self.phone = phone
        self.store = store
        self.bus = bus
        self.heartbeat = heartbeat_seconds
        self.extra_blocklist = extra_blocklist or []
        self.app = FastAPI(title="Nixin Link", docs_url=None, redoc_url=None, openapi_url=None)
        self.app.add_api_route("/health", self.health, methods=["GET"])
        self.app.add_api_websocket_route("/link", self.link)

    async def health(self) -> dict:
        return {"ok": True, "name": "nixin", "version": __version__, "protocol": PROTOCOL_VERSION,
                "phone": self.phone.connected}

    async def link(self, ws: WebSocket) -> None:
        await ws.accept()
        peer = f"{ws.client.host}:{ws.client.port}" if ws.client else "?"
        nonce = new_nonce()
        await ws.send_text(json.dumps({
            "t": "hello", "v": PROTOCOL_VERSION, "pcId": self.identity.pc_id,
            "pcName": self.identity.pc_name, "nonce": nonce, "server": __version__,
        }))
        try:
            first = json.loads(await asyncio.wait_for(ws.receive_text(), timeout=15))
        except (TimeoutError, json.JSONDecodeError, WebSocketDisconnect):
            await self._deny(ws, "auth.timeout", "No valid hello reply", CLOSE_TIMEOUT)
            return

        session = await self._authenticate(ws, first, nonce, peer)
        if session is None:
            return

        await self.phone.attach(session)
        hb = asyncio.create_task(self._heartbeat(session))
        reason = "closed"
        try:
            while True:
                raw = await ws.receive_text()
                if len(raw) > MAX_FRAME:
                    reason = "frame too large"
                    break
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(msg, dict):
                    await self.phone.handle_message(session, msg)
        except WebSocketDisconnect as e:
            reason = f"disconnect {e.code}"
        except Exception as e:  # noqa: BLE001
            reason = f"error {e!r}"
        finally:
            hb.cancel()
            await self.phone.detach(session, reason)
            self.store.touch_device(session.device_id)
            self.bus.emit("log", level="info", msg=f"Phone {session.device.get('name')} disconnected ({reason})")

    async def _authenticate(self, ws: WebSocket, msg: dict, nonce: str, peer: str) -> PhoneSession | None:
        t = msg.get("t")
        device_id = str(msg.get("deviceId", ""))[:64]
        if not device_id:
            await self._deny(ws, "bad_request", "deviceId missing")
            return None

        if t == "pair":
            token = str(msg.get("token", ""))
            pub = str(msg.get("publicKey", ""))
            sig = str(msg.get("sig", ""))
            if not self.pairing.is_valid(token):
                await self._deny(ws, "auth.invalid_token", "Pairing code is invalid, used or expired. Create a new QR.")
                self.bus.emit("log", level="warning", msg=f"Rejected pairing from {peer}: bad token")
                return None
            if not verify_signature(pub, pair_message(self.identity.pc_id, nonce, token, device_id), sig):
                await self._deny(ws, "auth.bad_signature", "Signature check failed")
                return None
            self.pairing.consume(token)
            device = {
                "name": str(msg.get("deviceName", "Android"))[:80],
                "model": str(msg.get("model", ""))[:80],
                "sdk": msg.get("sdk"),
                "appVersion": str(msg.get("appVersion", ""))[:20],
            }
            self.store.add_device(device_id, device["name"], device["model"], pub)
            self.bus.emit("paired", deviceId=device_id, device=device)
            self.bus.emit("log", level="info", msg=f"Paired new phone: {device['name']} ({device['model']})")
            paired = True
        elif t == "auth":
            rec = self.store.get_device(device_id)
            if rec is None:
                await self._deny(ws, "auth.unknown_device", "This phone is not paired (or was removed). Scan a new QR.")
                return None
            if not verify_signature(rec["public_key"], auth_message(self.identity.pc_id, nonce, device_id),
                                    str(msg.get("sig", ""))):
                await self._deny(ws, "auth.bad_signature", "Signature check failed")
                self.bus.emit("log", level="warning", msg=f"Bad signature from {peer} for {rec['name']}")
                return None
            device = {
                "name": rec["name"], "model": rec["model"], "sdk": msg.get("sdk"),
                "appVersion": str(msg.get("appVersion", ""))[:20],
            }
            self.store.touch_device(device_id)
            paired = False
        else:
            await self._deny(ws, "bad_request", "Expected pair or auth")
            return None

        session = PhoneSession(transport=_WsTransport(ws), device_id=device_id, device=device)
        await session.send({
            "t": "welcome", "v": PROTOCOL_VERSION, "sessionId": session.session_id, "paired": paired,
            "pcName": self.identity.pc_name, "heartbeatSec": self.heartbeat,
            "blocklist": self.extra_blocklist,
        })
        self.bus.emit("log", level="info", msg=f"Phone connected: {device['name']} from {peer}")
        return session

    async def _deny(self, ws: WebSocket, code: str, message: str, close_code: int = CLOSE_AUTH_FAILED) -> None:
        try:
            await ws.send_text(json.dumps({"t": "denied", "code": code, "message": message}))
            await ws.close(code=close_code, reason=code)
        except Exception:
            pass

    async def _heartbeat(self, session: PhoneSession) -> None:
        try:
            while not session.closed:
                await asyncio.sleep(self.heartbeat)
                if time.time() - session.last_rx > self.heartbeat * 3:
                    self.bus.emit("log", level="warning", msg="Phone heartbeat lost; closing link")
                    await session.transport.close(CLOSE_TIMEOUT, "heartbeat timeout")
                    return
                await session.send({"t": "ping", "ts": int(time.time() * 1000)})
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
