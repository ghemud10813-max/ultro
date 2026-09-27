"""A stateful fake Android phone implementing every Nixin Link method.

Run ``nixin sim --pair "<nixin://pair?...>"`` to try the whole brain (router,
classifier, LangGraph agent, dashboard) without a real phone. It is also what the
end-to-end tests drive. The UI model is tiny but realistic enough for the agent:
a launcher, WhatsApp (chat list, chat, composer, Send), Instagram, YouTube search,
Settings with a Wi-Fi panel and a Display page with a Dark mode switch.
"""

from __future__ import annotations

import asyncio
import base64
import io
import re
import time
from dataclasses import dataclass, field
from typing import Any

from nixin.sim.client import SimError

BLOCKED = {"com.google.android.apps.nbu.paisa.user", "net.one97.paytm", "com.phonepe.app", "com.sbi.lotusintouch"}
SENSITIVE_WORDS = re.compile(r"\b(send|post|share|pay|buy|order|delete|remove|transfer|call|submit|bhejo)\b", re.I)
SENSITIVE_PACKAGES = {"com.whatsapp", "com.instagram.android", "com.google.android.gm", "org.telegram.messenger"}


@dataclass
class El:
    role: str
    text: str | None = None
    desc: str | None = None
    hint: str | None = None
    res: str | None = None
    b: tuple[int, int, int, int] = (0, 0, 100, 100)
    flags: tuple[str, ...] = ("click",)
    checked: bool | None = None
    on_tap: Any = None  # callable(sim) -> None
    key: str = ""  # stable identity for editable fields


@dataclass
class Screen:
    package: str
    app: str
    title: str | None
    elements: list[El]
    keyboard: bool = False


@dataclass
class SimPhone:
    name: str = "Nixin Simulator"
    volumes: dict = field(default_factory=lambda: {"media": [7, 15], "ring": [10, 15], "alarm": [12, 15],
                                                   "notification": [8, 15], "call": [4, 5]})
    muted: bool = False
    torch: bool = False
    brightness: int = 60
    auto_brightness: bool = False
    ringer: str = "normal"
    dnd: bool = False
    battery: int = 78
    stopped: bool = False
    locked: bool = False
    allow_screenshots: bool = True
    wifi: bool = True
    dark_mode: bool = False
    media_state: str = "paused"
    apps: list[dict] = field(default_factory=lambda: [
        {"label": "WhatsApp", "package": "com.whatsapp"},
        {"label": "Instagram", "package": "com.instagram.android"},
        {"label": "YouTube", "package": "com.google.android.youtube"},
        {"label": "Settings", "package": "com.android.settings"},
        {"label": "Clock", "package": "com.google.android.deskclock"},
        {"label": "Chrome", "package": "com.android.chrome"},
        {"label": "Camera", "package": "com.android.camera2"},
        {"label": "Google Pay", "package": "com.google.android.apps.nbu.paisa.user"},
    ])
    contacts: list[dict] = field(default_factory=lambda: [
        {"id": "1", "name": "Rahul Sharma", "numbers": [{"number": "+91 98765 43210", "label": "Mobile"}]},
        {"id": "2", "name": "Rahul Verma", "numbers": [{"number": "+91 91234 56780", "label": "Mobile"}]},
        {"id": "3", "name": "Mummy", "numbers": [{"number": "+91 99999 11111", "label": "Mobile"}]},
        {"id": "4", "name": "Priya", "numbers": [{"number": "+91 88888 22222", "label": "Mobile"}]},
    ])
    notifications: list[dict] = field(default_factory=lambda: [
        {"key": "n1", "package": "com.instagram.android", "app": "Instagram", "title": "priya_k",
         "text": "liked your photo", "time": int(time.time() * 1000) - 60_000},
        {"key": "n2", "package": "com.whatsapp", "app": "WhatsApp", "title": "Mummy", "text": "Khana kha liya?",
         "time": int(time.time() * 1000) - 300_000},
    ])
    alarms: list[dict] = field(default_factory=list)
    timers: list[dict] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    sms: list[dict] = field(default_factory=list)
    whatsapp_sent: list[dict] = field(default_factory=list)
    opened_urls: list[str] = field(default_factory=list)
    liked_post: bool = False
    history: list[str] = field(default_factory=list)  # method log

    # UI state
    screen_name: str = "home"
    chat_with: str | None = None
    compose_text: str = ""
    search_query: str = ""
    focused: str | None = None
    _snap_id: int = 0
    _snap_map: dict[int, El] = field(default_factory=dict)

    # ------------------------------------------------------------------ screens
    def screen(self) -> Screen:
        n = self.screen_name
        if n == "home":
            els = [El("text", "12:30", res="clock", flags=())]
            for i, a in enumerate(self.apps[:7]):
                els.append(El("button", a["label"], b=(40 + (i % 4) * 250, 1500 + (i // 4) * 300, 240 + (i % 4) * 250, 1700 + (i // 4) * 300),
                              on_tap=lambda s, p=a["package"]: s.open_package(p)))
            return Screen("com.android.launcher3", "Launcher", None, els)
        if n == "wa_chats":
            els = [El("text", "WhatsApp", flags=(), b=(40, 100, 400, 180)),
                   El("button", desc="Search", b=(900, 100, 1000, 180), on_tap=lambda s: s.go("wa_search")),
                   El("list", flags=("scroll",), b=(0, 250, 1080, 2200))]
            for i, c in enumerate(["Rahul Sharma", "Mummy", "Priya"]):
                els.append(El("item", c, b=(0, 260 + i * 180, 1080, 430 + i * 180), on_tap=lambda s, c=c: s.open_chat(c)))
            return Screen("com.whatsapp", "WhatsApp", "WhatsApp", els)
        if n == "wa_search":
            els = [El("button", desc="Back", b=(0, 100, 100, 180), on_tap=lambda s: s.go("wa_chats")),
                   El("input", self.search_query or None, hint="Search…", key="wa_search", flags=("click", "edit", "focus"),
                      b=(120, 100, 1000, 180))]
            for i, c in enumerate(x for x in ["Rahul Sharma", "Mummy", "Priya"] if self.search_query.lower() in x.lower()):
                els.append(El("item", c, b=(0, 260 + i * 180, 1080, 430 + i * 180), on_tap=lambda s, c=c: s.open_chat(c)))
            return Screen("com.whatsapp", "WhatsApp", None, els, keyboard=True)
        if n == "wa_chat":
            els = [El("button", desc="Navigate up", b=(0, 100, 100, 180), on_tap=lambda s: s.go("wa_chats")),
                   El("text", self.chat_with, res="conversation_contact_name", flags=("click",), b=(120, 100, 700, 180))]
            for i, m in enumerate([m for m in self.whatsapp_sent if m["name"] == self.chat_with][-3:]):
                els.append(El("text", m["text"], flags=(), b=(300, 1500 + i * 120, 1050, 1600 + i * 120)))
            els.append(El("input", self.compose_text or None, hint="Message", res="entry", key="wa_entry",
                          flags=("click", "edit") + (("focus",) if self.focused == "wa_entry" else ()), b=(40, 2200, 900, 2300)))
            if self.compose_text:
                els.append(El("button", desc="Send", res="send", b=(930, 2200, 1060, 2300), on_tap=lambda s: s.wa_send()))
            return Screen("com.whatsapp", "WhatsApp", self.chat_with, els, keyboard=self.focused == "wa_entry")
        if n == "ig_home":
            return Screen("com.instagram.android", "Instagram", None, [
                El("button", desc="Notifications", b=(900, 100, 1000, 180), on_tap=lambda s: s.go("ig_activity")),
                El("text", "priya_k", flags=(), b=(40, 300, 400, 360)),
                El("image", desc="Photo by priya_k", flags=("click",), b=(0, 380, 1080, 1400)),
                El("button", desc="Liked" if self.liked_post else "Like", b=(40, 1420, 140, 1500),
                   on_tap=lambda s: setattr(s, "liked_post", True)),
                El("list", flags=("scroll",), b=(0, 200, 1080, 2200)),
            ])
        if n == "ig_activity":
            return Screen("com.instagram.android", "Instagram", "Activity", [
                El("button", desc="Back", b=(0, 100, 100, 180), on_tap=lambda s: s.go("ig_home")),
                El("text", "Activity", flags=(), b=(120, 100, 500, 180)),
                El("item", "priya_k liked your photo. 1m", b=(0, 250, 1080, 400)),
            ])
        if n == "yt_results":
            return Screen("com.google.android.youtube", "YouTube", None, [
                El("input", self.search_query, key="yt_search", flags=("click", "edit"), b=(100, 100, 900, 180)),
                El("item", f"{self.search_query} - Official Video", desc=f"{self.search_query} - Official Video - 12M views",
                   b=(0, 300, 1080, 900), on_tap=lambda s: s.play()),
                El("item", f"{self.search_query} (Lyrics)", b=(0, 950, 1080, 1500), on_tap=lambda s: s.play()),
            ])
        if n == "yt_player":
            return Screen("com.google.android.youtube", "YouTube", None, [
                El("text", f"Now playing: {self.search_query}", flags=(), b=(0, 700, 1080, 800)),
                El("button", desc="Pause video", b=(490, 400, 590, 500), on_tap=lambda s: setattr(s, "media_state", "paused")),
            ])
        if n == "settings_wifi":
            return Screen("com.android.settings", "Settings", "Internet", [
                El("text", "Wi-Fi", flags=(), b=(40, 300, 700, 380)),
                El("switch", None, desc="Wi-Fi", flags=("click",), checked=self.wifi, b=(900, 300, 1040, 380),
                   on_tap=lambda s: setattr(s, "wifi", not s.wifi)),
                El("button", "Done", b=(800, 1200, 1040, 1300), on_tap=lambda s: s.go("home")),
            ])
        if n == "settings_main":
            return Screen("com.android.settings", "Settings", "Settings", [
                El("item", "Connections", b=(0, 300, 1080, 420)),
                El("item", "Display", b=(0, 440, 1080, 560), on_tap=lambda s: s.go("settings_display")),
                El("item", "Battery", b=(0, 580, 1080, 700)),
                El("list", flags=("scroll",), b=(0, 250, 1080, 2200)),
            ])
        if n == "settings_display":
            return Screen("com.android.settings", "Settings", "Display", [
                El("button", desc="Navigate up", b=(0, 100, 100, 180), on_tap=lambda s: s.go("settings_main")),
                El("text", "Dark mode", flags=(), b=(40, 300, 700, 380)),
                El("switch", None, desc="Dark mode", flags=("click",), checked=self.dark_mode, b=(900, 300, 1040, 380),
                   on_tap=lambda s: setattr(s, "dark_mode", not s.dark_mode)),
            ])
        return Screen(self.foreground_package(), self.app_label(self.foreground_package()), None,
                      [El("text", f"{self.app_label(self.foreground_package())} home", flags=())])

    # ------------------------------------------------------------------ UI helpers
    def go(self, name: str) -> None:
        self.screen_name = name
        self.focused = None

    def foreground_package(self) -> str:
        n = self.screen_name
        if n.startswith("wa_"):
            return "com.whatsapp"
        if n.startswith("ig_"):
            return "com.instagram.android"
        if n.startswith("yt_"):
            return "com.google.android.youtube"
        if n.startswith("settings"):
            return "com.android.settings"
        if n.startswith("app:"):
            return n[4:]
        return "com.android.launcher3"

    def app_label(self, pkg: str) -> str:
        return next((a["label"] for a in self.apps if a["package"] == pkg), "Launcher" if "launcher" in pkg else pkg)

    def open_package(self, pkg: str) -> None:
        self.go({"com.whatsapp": "wa_chats", "com.instagram.android": "ig_home", "com.android.settings": "settings_main",
                 "com.google.android.youtube": "yt_results"}.get(pkg, f"app:{pkg}"))

    def open_chat(self, name: str) -> None:
        self.chat_with, self.compose_text = name, ""
        self.go("wa_chat")

    def wa_send(self) -> None:
        if self.compose_text and self.chat_with:
            number = next((c["numbers"][0]["number"] for c in self.contacts if c["name"] == self.chat_with), "")
            self.whatsapp_sent.append({"name": self.chat_with, "number": number, "text": self.compose_text, "via": "ui"})
            self.compose_text = ""

    def play(self) -> None:
        self.media_state = "playing"
        self.go("yt_player")

    # ------------------------------------------------------------------ snapshot
    def snapshot(self, max_elements: int = 150) -> dict:
        scr = self.screen()
        self._snap_id += 1
        self._snap_map = {}
        out = []
        for i, e in enumerate(scr.elements[:max_elements], start=1):
            self._snap_map[i] = e
            d: dict = {"id": i, "role": e.role, "b": list(e.b), "flags": list(e.flags)}
            for k in ("text", "desc", "hint", "res"):
                if getattr(e, k):
                    d[k] = getattr(e, k)
            if e.checked is not None:
                d["checked"] = e.checked
            out.append(d)
        return {"snapshotId": f"s{self._snap_id}", "package": scr.package, "app": scr.app, "title": scr.title,
                "width": 1080, "height": 2400, "keyboard": scr.keyboard, "truncated": len(scr.elements) > max_elements,
                "elements": out}

    def _element(self, params: dict) -> El:
        sid = params.get("snapshotId")
        if sid and sid != f"s{self._snap_id}":
            raise SimError("target.stale", "Snapshot is out of date")
        e = self._snap_map.get(int(params.get("elementId", -1)))
        if e is None:
            raise SimError("target.not_found", "No such element")
        return e

    # ------------------------------------------------------------------ method handler
    async def handle(self, method: str, p: dict, meta: dict) -> dict:
        self.history.append(method)
        await asyncio.sleep(0.005)
        if self.stopped and method not in ("device.status", "app.list"):
            raise SimError("policy.stopped")
        fg = self.foreground_package()
        if method.startswith("ui.") or method == "screen.capture":
            if self.locked:
                raise SimError("device.locked")
            if fg in BLOCKED:
                raise SimError("policy.blocked_app")

        match method:
            case "device.status":
                return {"battery": {"level": self.battery, "charging": False},
                        "volume": {k: {"level": v[0], "max": v[1]} for k, v in self.volumes.items()},
                        "ringer": self.ringer, "torch": self.torch, "screenOn": True, "locked": self.locked,
                        "foreground": {"package": fg, "label": self.app_label(fg)}, "dnd": self.dnd,
                        "stopped": self.stopped,
                        "permissions": {"accessibility": True, "notifications": True, "contacts": True, "call": True,
                                        "sms": True, "writeSettings": True, "dnd": True},
                        "settings": {"allowScreenshots": self.allow_screenshots},
                        "device": {"model": "sim", "manufacturer": "nixin", "sdk": 34, "appVersion": "sim"}}
            case "device.volume":
                stream = p.get("stream", "media")
                cur, mx = self.volumes[stream]
                prev = cur
                a = p["action"]
                if a == "up":
                    cur = min(mx, cur + p.get("steps", 1))
                elif a == "down":
                    cur = max(0, cur - p.get("steps", 1))
                elif a == "set":
                    cur = round(mx * p.get("percent", 50) / 100)
                elif a == "max":
                    cur = mx
                elif a == "mute":
                    self.muted = True
                elif a == "unmute":
                    self.muted = False
                self.volumes[stream][0] = cur
                return {"stream": stream, "previous": prev, "current": cur, "max": mx}
            case "device.torch":
                self.torch = bool(p["on"])
                return {"on": self.torch}
            case "device.brightness":
                prev = self.brightness
                a = p["action"]
                if a == "auto":
                    self.auto_brightness = True
                elif a == "set":
                    self.brightness, self.auto_brightness = p.get("percent", 50), False
                elif a == "up":
                    self.brightness = min(100, self.brightness + 20)
                elif a == "down":
                    self.brightness = max(0, self.brightness - 20)
                return {"previous": prev, "current": self.brightness, "auto": self.auto_brightness}
            case "device.ringer":
                self.ringer = p["mode"]
                return {"mode": self.ringer}
            case "device.dnd":
                self.dnd = bool(p["on"])
                return {"on": self.dnd}
            case "device.global":
                a = p["action"]
                if a == "back":
                    self.go({"wa_chat": "wa_chats", "wa_search": "wa_chats", "ig_activity": "ig_home",
                             "settings_display": "settings_main", "yt_player": "yt_results"}.get(self.screen_name, "home"))
                elif a == "home":
                    self.go("home")
                return {"action": a}
            case "device.settings":
                self.go("settings_wifi" if p["panel"] in ("wifi", "internet") else "settings_main")
                return {"opened": p["panel"]}
            case "app.list":
                return {"apps": self.apps}
            case "app.current":
                return {"package": fg, "label": self.app_label(fg)}
            case "app.open":
                pkg = p.get("package")
                if not pkg:
                    name = p["name"].lower()
                    pkg = next((a["package"] for a in self.apps if name in a["label"].lower()), None)
                if not pkg or pkg not in {a["package"] for a in self.apps}:
                    raise SimError("app.not_installed", "App not installed")
                if pkg in BLOCKED:
                    raise SimError("policy.blocked_app")
                self.open_package(pkg)
                return {"package": pkg, "label": self.app_label(pkg)}
            case "intent.url":
                self.opened_urls.append(p["url"])
                self.go("app:com.android.chrome")
                return {"opened": True}
            case "intent.search":
                self.search_query = p["query"]
                if p.get("engine") == "youtube":
                    self.go("yt_results")
                else:
                    self.go("app:com.android.chrome")
                self.opened_urls.append(f"search:{p.get('engine', 'web')}:{p['query']}")
                return {"opened": True}
            case "intent.navigate":
                self.opened_urls.append(f"nav:{p['destination']}")
                return {"opened": True}
            case "intent.alarm":
                self.alarms.append(dict(p))
                return {"hour": p["hour"], "minute": p["minute"]}
            case "intent.timer":
                self.timers.append(dict(p))
                return {"seconds": p["seconds"]}
            case "media.control":
                self.media_state = {"play": "playing", "pause": "paused", "stop": "stopped"}.get(p["action"], self.media_state)
                return {"action": p["action"]}
            case "contacts.search":
                q = p["query"].lower()
                found = [c for c in self.contacts if q in c["name"].lower()]
                return {"contacts": found[: p.get("limit", 5)]}
            case "comm.call":
                if not meta.get("confirmed"):
                    raise SimError("policy.confirmation_required")
                self.calls.append(p["number"])
                return {"number": p["number"], "mode": "call"}
            case "comm.sms":
                if not meta.get("confirmed"):
                    raise SimError("policy.confirmation_required")
                self.sms.append(dict(p))
                return {"number": p["number"], "mode": "sent"}
            case "comm.whatsapp":
                if not meta.get("confirmed"):
                    raise SimError("policy.confirmation_required")
                digits = re.sub(r"\D", "", p["number"])
                name = next((c["name"] for c in self.contacts
                             if re.sub(r"\D", "", c["numbers"][0]["number"]).endswith(digits[-10:])), p["number"])
                self.chat_with = name
                self.go("wa_chat")
                if p.get("send", True):
                    self.whatsapp_sent.append({"name": name, "number": p["number"], "text": p["text"], "via": "workflow"})
                    return {"state": "sent", "verified": True}
                self.compose_text = p["text"]
                return {"state": "composer", "verified": True}
            case "notif.list":
                items = [n for n in self.notifications if not p.get("package") or n["package"] == p["package"]]
                return {"notifications": items[: p.get("limit", 5)]}
            case "ui.snapshot":
                return self.snapshot(p.get("maxElements", 150))
            case "ui.tap" | "ui.long_press":
                if "elementId" in p:
                    e = self._element(p)
                    label = f"{e.text or ''} {e.desc or ''}"
                    if fg in SENSITIVE_PACKAGES and SENSITIVE_WORDS.search(label) and not meta.get("confirmed"):
                        raise SimError("policy.confirmation_required", f"'{label.strip()}' may send something")
                    if e.on_tap:
                        e.on_tap(self)
                    elif "edit" in e.flags:
                        self.focused = e.key
                    return {"tapped": e.text or e.desc or e.role}
                return {"tapped": [p["x"], p["y"]]}
            case "ui.type":
                if "elementId" in p:
                    e = self._element(p)
                else:
                    e = next((x for x in self._snap_map.values() if "edit" in x.flags and (self.focused in (None, x.key))), None)
                    if e is None:
                        raise SimError("target.not_editable", "No focused text field")
                if "edit" not in e.flags:
                    raise SimError("target.not_editable")
                self.focused = e.key
                text = p["text"] if p.get("clear", True) else (getattr(self, "compose_text", "") + p["text"])
                if e.key == "wa_entry":
                    self.compose_text = text
                elif e.key in ("wa_search", "yt_search"):
                    self.search_query = text
                    if e.key == "yt_search" and p.get("submit"):
                        self.go("yt_results")
                return {"typed": len(p["text"])}
            case "ui.scroll":
                return {"scrolled": p["direction"], "changed": False}
            case "ui.swipe":
                return {"swiped": True}
            case "ui.key":
                if p["key"] == "back":
                    return await self.handle("device.global", {"action": "back"}, meta)
                return {"key": p["key"]}
            case "ui.tap_text":
                self.snapshot()
                for i, e in self._snap_map.items():
                    if p["text"].lower() in f"{e.text or ''} {e.desc or ''}".lower():
                        return await self.handle("ui.tap", {"elementId": i}, meta)
                raise SimError("target.not_found")
            case "ui.wait":
                return {"matched": True}
            case "screen.capture":
                if not self.allow_screenshots:
                    raise SimError("policy.screenshots_disabled")
                return {"mime": "image/jpeg", "width": 360, "height": 800, "screenWidth": 1080, "screenHeight": 2400,
                        "data": _fake_jpeg()}
        raise SimError("unknown_method", method)


def _fake_jpeg() -> str:
    try:
        from PIL import Image

        img = Image.new("RGB", (360, 800), (30, 30, 40))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=50)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""
