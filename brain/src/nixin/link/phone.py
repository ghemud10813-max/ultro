"""PhoneLink: the brain's handle on the connected phone.

Everything that wants the phone to do something goes through ``PhoneLink.call``,
which validates params against the shared registry, attaches task metadata, writes
the audit log and turns error replies into ``PhoneError``.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from nixin.core.events import EventBus
from nixin.core.store import Store
from nixin.link.protocol import PhoneError, risk_of, validate_params


class Transport(Protocol):
    async def send_text(self, data: str) -> None: ...
    async def close(self, code: int = 1000, reason: str = "") -> None: ...


@dataclass
class PhoneSession:
    transport: Transport
    device_id: str
    device: dict
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    connected_at: float = field(default_factory=time.time)
    last_rx: float = field(default_factory=time.time)
    pending: dict[str, tuple[asyncio.Future, str]] = field(default_factory=dict)
    closed: bool = False
    _send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send(self, msg: dict) -> None:
        if self.closed:
            raise PhoneError("device.offline")
        async with self._send_lock:
            await self.transport.send_text(json.dumps(msg, ensure_ascii=False, separators=(",", ":")))


CommandHandler = Callable[[str, str, str | None], Awaitable[None]]  # text, source, message id
AnswerHandler = Callable[[str, str], None]  # ask id, value


class PhoneLink:
    def __init__(self, bus: EventBus, store: Store) -> None:
        self.bus = bus
        self.store = store
        self.session: PhoneSession | None = None
        self.status: dict = {}
        self.apps: list[dict] = []
        self.on_command: CommandHandler | None = None
        self.on_answer: AnswerHandler | None = None
        self.on_stopped: Callable[[], None] | None = None
        # v2: inbound share/file messages from the phone's share sheet
        self.on_share: Callable[[dict], Awaitable[None]] | None = None
        self.on_file_chunk: Callable[[dict], Awaitable[None]] | None = None
        self.on_connected: Callable[[], Awaitable[None]] | None = None
        self._connected = asyncio.Event()

    # ------------------------------------------------------------------ state
    @property
    def connected(self) -> bool:
        return self.session is not None and not self.session.closed

    @property
    def stopped(self) -> bool:
        return bool(self.status.get("stopped"))

    @property
    def foreground(self) -> str | None:
        return (self.status.get("foreground") or {}).get("package")

    async def wait_connected(self, timeout: float | None = None) -> bool:
        try:
            await asyncio.wait_for(self._connected.wait(), timeout)
            return True
        except TimeoutError:
            return False

    def describe(self) -> dict:
        s = self.session
        return {
            "connected": self.connected,
            "device": s.device if s else None,
            "deviceId": s.device_id if s else None,
            "since": s.connected_at if s else None,
            "status": self.status,
            "apps": len(self.apps),
        }

    # ------------------------------------------------------------------ session lifecycle (called by server)
    async def attach(self, session: PhoneSession) -> None:
        old = self.session
        self.session = session
        self._connected.set()
        if old and not old.closed:
            await self._fail_pending(old, "device.offline")
            old.closed = True
            try:
                await old.transport.close(4000, "replaced by a new connection")
            except Exception:
                pass
        self.bus.emit("phone", connected=True, device=session.device, deviceId=session.device_id)
        self.bus.emit("device_event", name="phone_connected", data={"device": session.device})
        asyncio.create_task(self._initial_sync())

    async def detach(self, session: PhoneSession, reason: str = "") -> None:
        session.closed = True
        await self._fail_pending(session, "device.offline")
        if self.session is session:
            self.session = None
            self._connected.clear()
            self.bus.emit("phone", connected=False, reason=reason)
            self.bus.emit("device_event", name="phone_disconnected", data={"reason": reason})

    async def _fail_pending(self, session: PhoneSession, code: str) -> None:
        for _id, (fut, method) in list(session.pending.items()):
            if not fut.done():
                # An external side effect that was in flight may or may not have happened.
                if risk_of(method) == "external":
                    fut.set_exception(PhoneError("action.uncertain", "Phone disconnected while the action was running."))
                else:
                    fut.set_exception(PhoneError(code))
        session.pending.clear()

    async def _initial_sync(self) -> None:
        try:
            self.status = await self.call("device.status", {}, timeout=10, origin="link")
            self.bus.emit("phone_status", status=self.status)
        except Exception:
            pass
        try:
            res = await self.call("app.list", {}, timeout=15, origin="link")
            self.apps = res.get("apps", [])
        except Exception:
            pass
        if self.on_connected:
            try:
                await self.on_connected()
            except Exception:
                pass

    # ------------------------------------------------------------------ inbound
    async def handle_message(self, session: PhoneSession, msg: dict) -> None:
        session.last_rx = time.time()
        t = msg.get("t")
        if t == "res":
            entry = session.pending.pop(str(msg.get("id")), None)
            if entry:
                fut, _method = entry
                if not fut.done():
                    if msg.get("ok"):
                        fut.set_result(msg.get("result") or {})
                    else:
                        err = msg.get("error") or {}
                        fut.set_exception(
                            PhoneError(str(err.get("code", "internal")), str(err.get("message", "")), err.get("details"))
                        )
        elif t == "ping":
            await session.send({"t": "pong", "ts": msg.get("ts")})
        elif t == "pong":
            pass
        elif t == "event":
            await self._handle_event(msg.get("name", ""), msg.get("data") or {})
        elif t == "cmd":
            text = str(msg.get("text", "")).strip()
            source = str(msg.get("source", "phone_text"))
            if source not in ("phone_text", "phone_voice"):
                source = "phone_text"
            if text and self.on_command:
                asyncio.create_task(self.on_command(text, source, msg.get("id")))
        elif t == "answer":
            if self.on_answer:
                self.on_answer(str(msg.get("id")), str(msg.get("value", "")))
        elif t == "share":
            if self.on_share:
                asyncio.create_task(self.on_share(msg))
        elif t == "file":
            if self.on_file_chunk:
                await self.on_file_chunk(msg)
        else:
            self.bus.emit("log", level="warning", msg=f"Unknown message from phone: {t!r}")

    async def _handle_event(self, name: str, data: dict) -> None:
        # one uniform stream for routines / dashboard, in addition to the specific handling below
        self.bus.emit("device_event", name=name, data=data)
        if name == "battery":
            self.status["battery"] = {**(self.status.get("battery") or {}), **data}
            self.bus.emit("phone_status", status=self.status)
            return
        if name == "status":
            self.status.update(data)
            self.bus.emit("phone_status", status=self.status)
        elif name == "stopped":
            self.status["stopped"] = True
            self.bus.emit("phone_status", status=self.status)
            self.bus.emit("log", level="warning", msg="Kill switch activated on the phone.")
            if self.on_stopped:
                self.on_stopped()
        elif name == "resumed":
            self.status["stopped"] = False
            self.bus.emit("phone_status", status=self.status)
            self.bus.emit("log", level="info", msg="Phone resumed automation.")
        elif name == "foreground":
            self.status["foreground"] = data
            self.bus.emit("phone_status", status=self.status)
        elif name == "apps":
            self.apps = data.get("apps", self.apps)
        elif name == "notification":
            self.bus.emit("notification", notification=data)
        elif name == "notification_removed":
            self.bus.emit("notification_removed", key=data.get("key"))
        elif name == "recorded_step":
            self.bus.emit("recorded_step", step=data)
        else:
            self.bus.emit("phone_event", name=name, data=data)

    # ------------------------------------------------------------------ outbound
    async def call(
        self,
        method: str,
        params: dict | None = None,
        *,
        timeout: float = 15.0,
        task_id: str | None = None,
        origin: str = "brain",
        confirmed: bool = False,
    ) -> dict:
        params = params or {}
        validate_params(method, params)
        risk = risk_of(method)
        session = self.session
        if session is None or session.closed:
            raise PhoneError("device.offline")
        if self.stopped and method not in ("device.status", "app.list", "device.info", "rec.stop"):
            raise PhoneError("policy.stopped")

        req_id = str(uuid.uuid4())
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        session.pending[req_id] = (fut, method)
        msg = {
            "t": "req",
            "id": req_id,
            "method": method,
            "params": params,
            "timeoutMs": int(timeout * 1000),
            "meta": {"taskId": task_id, "origin": origin, "confirmed": bool(confirmed)},
        }
        started = time.time()
        ok: bool | None = None
        detail: dict[str, Any] = {"params": _redact_params(method, params)}
        try:
            await session.send(msg)
            # small grace so the phone's own timeout wins and returns a proper error
            result = await asyncio.wait_for(fut, timeout + 3)
            ok = True
            detail["result"] = _short(result)
            return result
        except TimeoutError:
            session.pending.pop(req_id, None)
            ok = False
            code = "action.uncertain" if risk == "external" else "timeout"
            detail["error"] = code
            raise PhoneError(code, f"{method} timed out") from None
        except PhoneError as e:
            ok = False
            detail["error"] = e.code
            raise
        finally:
            detail["ms"] = int((time.time() - started) * 1000)
            if method not in ("device.status", "screen.capture", "app.list", "file.push", "ui.snapshot"):
                self.store.audit(method, risk, origin, ok, detail, task_id)
                self.bus.emit("action", method=method, risk=risk, origin=origin, ok=ok, taskId=task_id,
                              ms=detail["ms"], error=detail.get("error"))

    async def send_message(self, msg: dict) -> bool:
        """Fire-and-forget message (say / ask / task / cancel). Returns False when offline."""
        if not self.connected:
            return False
        try:
            await self.session.send(msg)  # type: ignore[union-attr]
            return True
        except Exception:
            return False

    async def say(self, text: str, *, speak: bool = True, task_id: str | None = None) -> bool:
        return await self.send_message({"t": "say", "text": text, "speak": speak, "taskId": task_id})

    async def cancel(self, task_id: str | None, reason: str = "user") -> None:
        await self.send_message({"t": "cancel", "taskId": task_id, "reason": reason})

    async def refresh_status(self) -> dict:
        self.status = await self.call("device.status", {}, timeout=8, origin="link")
        self.bus.emit("phone_status", status=self.status)
        return self.status


def _redact_params(method: str, params: dict) -> dict:
    p = dict(params)
    if "text" in p and method in ("comm.sms", "comm.whatsapp", "ui.type"):
        t = str(p["text"])
        p["text"] = t if len(t) <= 40 else t[:37] + "..."
    return p


def _short(result: dict) -> dict:
    s = json.dumps(result, default=str)
    if len(s) <= 600:
        return result
    keys = {k: (v if len(json.dumps(v, default=str)) < 120 else "…") for k, v in result.items()}
    return keys
