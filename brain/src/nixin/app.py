"""Composition root: builds every component and runs the servers in one asyncio loop."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from nixin.adb.power import AdbPower
from nixin.config import NixinConfig
from nixin.core.actions import Actions
from nixin.core.brain import Brain
from nixin.core.confirm import ConfirmationGate
from nixin.core.events import EventBus
from nixin.core.memory import Memory
from nixin.core.serve import EmbeddedServer
from nixin.core.store import Store
from nixin.link.phone import PhoneLink
from nixin.link.server import LinkServer
from nixin.llm.gateway import Gateway
from nixin.security.certs import ensure_identity, local_ips
from nixin.security.pairing import PairingManager, PairingOffer

log = logging.getLogger("nixin")

# Settings the dashboard may change at runtime (persisted in SQLite, applied on start).
RUNTIME_SETTINGS = {
    "privacy.cloud_llm": bool,
    "privacy.cloud_stt": bool,
    "privacy.cloud_vision": bool,
    "assistant.confirm": str,
    "assistant.reply_on": str,
    "assistant.reply_language": str,
    "assistant.verify_finish": bool,
    "assistant.max_agent_steps": int,
    "assistant.default_message_channel": str,
    "voice.wake_word": bool,
    "voice.follow_up_seconds": float,
    "assistant.city": str,
    "assistant.announce_on": str,
    "notifications.announce": bool,
    "notifications.toast_on_pc": bool,
    "notifications.vip": list,
    "notifications.announce_apps": list,
    "bridge.clipboard_on_share": bool,
    "bridge.open_links": bool,
}


def apply_setting(cfg: NixinConfig, key: str, value: Any) -> None:
    if key not in RUNTIME_SETTINGS:
        raise KeyError(key)
    section, name = key.split(".", 1)
    obj = getattr(cfg, section)
    typ = RUNTIME_SETTINGS[key]
    # validate through pydantic by rebuilding the section
    data = obj.model_dump()
    if typ is list:
        items = value.split(",") if isinstance(value, str) else list(value)
        data[name] = [str(v).strip() for v in items if str(v).strip()]
    else:
        data[name] = typ(value)
    setattr(cfg, section, type(obj).model_validate(data))


class NixinApp:
    def __init__(self, cfg: NixinConfig, *, http: httpx.AsyncClient | None = None, db_path: str | None = None) -> None:
        self.cfg = cfg
        self.bus = EventBus()
        self.store = Store(db_path or (cfg.data_path / "nixin.db"))
        for key, value in (self.store.get_setting("overrides", {}) or {}).items():
            try:
                apply_setting(cfg, key, value)
            except Exception:
                pass
        self.identity = ensure_identity(cfg.data_path, cfg.pc.name)
        self.pairing = PairingManager(self.identity.pc_id, self.identity.pc_name, self.identity.fingerprint,
                                      ttl_seconds=cfg.link.pairing_minutes * 60)
        self.phone = PhoneLink(self.bus, self.store)
        self.link = LinkServer(self.identity, self.pairing, self.phone, self.store, self.bus,
                               cfg.link.heartbeat_seconds, cfg.blocklist.extra_packages)
        self.http = http or httpx.AsyncClient(timeout=20)
        self.gateway = Gateway(cfg, self.store, self.bus, self.http)
        self.memory = Memory(self.store)
        self.gate = ConfirmationGate(self.bus, cfg.assistant.confirm_timeout_seconds)
        self.adb = AdbPower(cfg.adb, self.bus)
        self.actions = Actions(cfg, self.phone, self.memory, self.gate, self.bus, self.adb)
        self.brain = Brain(cfg, self.store, self.bus, self.phone, self.gateway, self.memory, self.gate, self.actions)
        self.brain.app = self
        from nixin.features import install_features

        self.features = install_features(self)
        self.phone.on_connected = self._on_phone_connected
        self.voice = None
        self.dashboard = None
        self.dashboard_token: str | None = None
        self._servers: list[EmbeddedServer] = []
        self.link_server: EmbeddedServer | None = None
        self.store.purge_older_than(30)

    # ------------------------------------------------------------------ pairing
    def endpoints(self, port: int | None = None) -> list[str]:
        port = port or (self.link_server.port if self.link_server else self.cfg.link.port)
        hosts: list[str] = []
        if self.cfg.link.host not in ("0.0.0.0", "", "::"):
            hosts.append(self.cfg.link.host)
        hosts += [ip for ip in local_ips() if ip not in hosts]
        hosts += [h for h in self.cfg.link.advertise if h not in hosts]
        if not hosts:
            hosts = ["127.0.0.1"]
        return [f"wss://{h}:{port}/link" for h in hosts]

    def new_pairing(self) -> PairingOffer:
        offer = self.pairing.create(self.endpoints())
        self.bus.emit("pairing", uri=offer.uri, expires=offer.expires_at, endpoints=offer.payload["endpoints"])
        return offer

    def set_setting(self, key: str, value: Any) -> None:
        apply_setting(self.cfg, key, value)
        overrides = self.store.get_setting("overrides", {}) or {}
        overrides[key] = value
        self.store.set_setting("overrides", overrides)
        self.bus.emit("settings", key=key, value=value)

    # ------------------------------------------------------------------ lifecycle
    async def start(self, *, with_voice: bool | None = None, with_dashboard: bool | None = None) -> None:
        self.link_server = EmbeddedServer(self.link.app, self.cfg.link.host, self.cfg.link.port,
                                          str(self.identity.cert_path), str(self.identity.key_path))
        await self.link_server.start()
        self._servers.append(self.link_server)
        self.bus.emit("log", level="info", msg=f"Phone link listening on {', '.join(self.endpoints())}")

        if with_dashboard if with_dashboard is not None else self.cfg.dashboard.enabled:
            from nixin.dashboard.server import Dashboard

            self.dashboard = Dashboard(self)
            self.dashboard_token = self.dashboard.token
            srv = EmbeddedServer(self.dashboard.app, self.cfg.dashboard.host, self.cfg.dashboard.port)
            await srv.start()
            self._servers.append(srv)
            self.bus.emit("log", level="info", msg=f"Dashboard: {self.dashboard_url(srv.port)}")

        if with_voice if with_voice is not None else self.cfg.voice.enabled:
            try:
                from nixin.voice.loop import VoiceLoop

                self.voice = VoiceLoop(self)
                await self.voice.start()
            except Exception as e:  # noqa: BLE001 — voice is optional
                self.voice = None
                self.bus.emit("log", level="warning", msg=f"Voice disabled: {e}")

        for f in self.features:
            await f.start()
        asyncio.create_task(self._probe())

    def dashboard_url(self, port: int | None = None) -> str:
        port = port or self.cfg.dashboard.port
        return f"http://{self.cfg.dashboard.host}:{port}/?token={self.dashboard_token}"

    async def _probe(self) -> None:
        try:
            report = await self.gateway.probe()
            self.bus.emit("providers", report=report, status=self.gateway.status())
        except Exception as e:  # noqa: BLE001
            self.bus.emit("log", level="warning", msg=f"Provider probe failed: {e}")

    async def _on_phone_connected(self) -> None:
        """Send the phone its quick-action chips (scenes + taught skills)."""
        chips = [{"label": p["name"], "text": p["phrase"]} for p in self.routines.phrases()]
        chips += [{"label": s.name, "text": f"{s.name} chalao"} for s in self.skills.list() if s.kind == "taught"]
        await self.phone.send_message({"t": "scenes", "items": chips[:16]})

    async def stop(self) -> None:
        for f in reversed(getattr(self, "features", [])):
            try:
                await f.stop()
            except Exception:  # noqa: BLE001
                pass
        if self.voice:
            await self.voice.stop()
        for s in reversed(self._servers):
            await s.stop()
        self._servers.clear()
        await self.gateway.aclose()
        self.store.close()
