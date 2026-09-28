"""High-level actions: turn intents into verified phone operations with spoken replies.

Used by three callers: the deterministic router, the LLM classifier and the phone
agent. Every external side effect (message, call, SMS) goes through
``_confirm_external`` and is sent with ``confirmed=True`` only after it passes.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime

from nixin.config import NixinConfig
from nixin.core.confirm import ConfirmationGate
from nixin.core.context import TRUSTED_TEXT_SOURCES, Outcome, TaskContext
from nixin.core.events import EventBus
from nixin.core.memory import Memory, match_app
from nixin.core.replies import duration_text, say
from nixin.link.phone import PhoneLink
from nixin.link.protocol import PhoneError, error_text
from nixin.router.router import Intent
from nixin.router.timeparse import ClockTime, describe_clock

_TOGGLE_WORDS = {
    "wifi": ["wi-fi", "wifi", "wlan"],
    "bluetooth": ["bluetooth"],
    "mobile_data": ["mobile data", "data", "cellular"],
    "hotspot": ["hotspot", "mobile hotspot"],
    "location": ["location", "use location"],
    "airplane": ["airplane", "flight", "aeroplane"],
    "nfc": ["nfc"],
}
_TOGGLE_PANEL = {"wifi": "wifi", "bluetooth": "bluetooth", "mobile_data": "internet", "hotspot": "hotspot",
                 "location": "location", "airplane": "airplane", "nfc": "nfc"}
_TOGGLE_LABEL = {"wifi": "Wi-Fi", "bluetooth": "Bluetooth", "mobile_data": "Mobile data", "hotspot": "Hotspot",
                 "location": "Location", "airplane": "Airplane mode", "nfc": "NFC"}
_ENGINE_LABEL = {"web": "Google", "youtube": "YouTube", "playstore": "Play Store", "maps": "Maps", "spotify": "Spotify"}


def normalize_number(raw: str, country_code: str = "91") -> str:
    digits = re.sub(r"[^\d+]", "", raw)
    if digits.startswith("+"):
        return digits
    digits = digits.lstrip("0") if len(digits) == 11 and digits.startswith("0") else digits
    if len(digits) == 10:
        return f"+{country_code}{digits}"
    if len(digits) > 10:
        return "+" + digits
    return digits


class Actions:
    def __init__(self, cfg: NixinConfig, phone: PhoneLink, memory: Memory, gate: ConfirmationGate, bus: EventBus,
                 adb=None) -> None:
        self.cfg = cfg
        self.phone = phone
        self.memory = memory
        self.gate = gate
        self.bus = bus
        self.adb = adb
        # v2 feature modules register handlers for their intent kinds here
        self.handlers: dict = {}

    # ------------------------------------------------------------------ helpers
    def _t(self, ctx: TaskContext, key: str, **kw) -> str:
        return say(key, ctx.lang, **kw)

    def error_outcome(self, e: Exception, ctx: TaskContext) -> Outcome:
        if isinstance(e, PhoneError):
            c = e.code
            if c == "device.offline":
                return Outcome(False, self._t(ctx, "offline"), code=c)
            if c == "policy.stopped":
                return Outcome(False, self._t(ctx, "stopped"), code=c)
            if c == "policy.blocked_app":
                return Outcome(False, self._t(ctx, "blocked"), code=c)
            if c == "device.locked":
                return Outcome(False, self._t(ctx, "locked"), code=c)
            if c.startswith("permission."):
                return Outcome(False, self._t(ctx, "permission", what=error_text(c)), code=c)
            if c == "action.uncertain":
                return Outcome(False, self._t(ctx, "message_uncertain"), uncertain=True, code=c)
            return Outcome(False, self._t(ctx, "failed", reason=e.message), code=c)
        return Outcome(False, self._t(ctx, "failed", reason=str(e)))

    async def call(self, ctx: TaskContext, method: str, params: dict, *, origin: str = "router",
                   confirmed: bool = False, timeout: float = 15.0) -> dict:
        return await self.phone.call(method, params, task_id=ctx.task_id, origin=origin, confirmed=confirmed,
                                     timeout=timeout)

    def _needs_confirm(self, ctx: TaskContext, deterministic: bool) -> bool:
        mode = self.cfg.assistant.confirm
        if mode == "always" or ctx.source == "wake_word":
            return True
        if ctx.source in ("routine", "plugin"):
            return not ctx.trusted
        if not deterministic:
            return True
        if ctx.source in TRUSTED_TEXT_SOURCES:
            return False
        return mode != "trusted"

    async def _confirm_external(self, ctx: TaskContext, question: str, deterministic: bool) -> Outcome | None:
        """None = approved; otherwise an Outcome explaining why not."""
        if not self._needs_confirm(ctx, deterministic):
            return None
        ans = await self.gate.ask(question, kind="confirm", task_id=ctx.task_id, source=ctx.source,
                                  timeout=self.cfg.assistant.confirm_timeout_seconds)
        if ans == "yes":
            return None
        return Outcome(False, self._t(ctx, "declined" if ans == "no" else "no_answer"), code="declined")

    # ------------------------------------------------------------------ dispatcher
    async def run_intent(self, intent: Intent, ctx: TaskContext, *, deterministic: bool = True,
                         origin: str = "router") -> Outcome:
        p = intent.params
        handler = self.handlers.get(intent.kind)
        try:
            if handler is not None:
                return await handler(intent, ctx, deterministic=deterministic, origin=origin)
            match intent.kind:
                case "phone":
                    return await self.phone_method(ctx, p["method"], p["params"], origin=origin)
                case "open_app":
                    return await self.open_app(ctx, p["name"], origin=origin)
                case "call":
                    return await self.call_contact(ctx, p["who"], deterministic=deterministic, origin=origin)
                case "message":
                    return await self.message(ctx, p.get("channel", "default"), p["who"], p["body"],
                                              deterministic=deterministic, origin=origin)
                case "toggle":
                    return await self.toggle(ctx, p["setting"], bool(p["on"]), origin=origin)
                case "notifications":
                    return await self.notifications(ctx, p.get("app"), int(p.get("limit") or 5), origin=origin)
                case "status":
                    return await self.status(ctx, p.get("what", "battery"))
                case "search":
                    return await self.search(ctx, p.get("engine", "web"), p["query"], bool(p.get("play")), origin=origin)
                case "navigate":
                    return await self.navigate(ctx, p["destination"], origin=origin)
                case "alarm":
                    return await self.alarm(ctx, int(p["hour"]), int(p["minute"]), p.get("day_hint"), p.get("label"),
                                            p.get("days"), origin=origin)
                case "timer":
                    return await self.timer(ctx, int(p["seconds"]), p.get("label"), origin=origin)
                case "remember":
                    self.memory.remember(p["fact"])
                    return Outcome(True, self._t(ctx, "remembered"))
                case "alias":
                    self.memory.set_contact_alias(p["alias"], p["name"], p.get("number"))
                    return Outcome(True, self._t(ctx, "alias_set", alias=p["alias"], name=p["name"]))
                case "clock":
                    now = datetime.now()
                    if p.get("what") == "date":
                        return Outcome(True, self._t(ctx, "date", date=now.strftime("%A, %d %B %Y")))
                    return Outcome(True, self._t(ctx, "time", time=now.strftime("%I:%M %p").lstrip("0")))
                case "chat":
                    return Outcome(True, self._t(ctx, p.get("kind", "greet")) if "text" not in p else p["text"])
                case "reply":
                    return Outcome(True, p["text"])
                case "clarify":
                    return Outcome(False, p["question"], code="clarify")
                case "agent":
                    return Outcome(True, "", followup_goal=p["goal"], followup_hint=p.get("hint"))
                case _:
                    return Outcome(False, self._t(ctx, "not_understood"))
        except PhoneError as e:
            return self.error_outcome(e, ctx)

    # ------------------------------------------------------------------ native
    async def phone_method(self, ctx: TaskContext, method: str, params: dict, origin: str = "router") -> Outcome:
        res = await self.call(ctx, method, params, origin=origin)
        lang = ctx.lang
        if method == "device.volume":
            if params.get("action") == "mute":
                return Outcome(True, say("volume_mute", lang), res)
            return Outcome(True, say("volume", lang, current=res.get("current", "?"), max=res.get("max", "?")), res)
        if method == "device.torch":
            return Outcome(True, say("torch_on" if res.get("on", params["on"]) else "torch_off", lang), res)
        if method == "device.brightness":
            if params.get("action") == "auto":
                return Outcome(True, say("brightness_auto", lang), res)
            return Outcome(True, say("brightness", lang, current=res.get("current", params.get("percent", "?"))), res)
        if method == "device.ringer":
            return Outcome(True, say("ringer", lang, mode=res.get("mode", params["mode"])), res)
        if method == "device.dnd":
            return Outcome(True, say("dnd_on" if params["on"] else "dnd_off", lang), res)
        if method == "device.global":
            return Outcome(True, say("global_" + params["action"], lang), res)
        if method == "device.settings":
            return Outcome(True, say("settings", lang, panel=params["panel"].replace("_", " ").title()), res)
        if method == "media.control":
            return Outcome(True, say("media_" + params["action"], lang), res)
        return Outcome(True, say("done", lang), res)

    async def open_app(self, ctx: TaskContext, name: str, origin: str = "router") -> Outcome:
        if not self.phone.apps and self.phone.connected:
            try:
                self.phone.apps = (await self.call(ctx, "app.list", {}, origin=origin)).get("apps", [])
            except PhoneError:
                pass
        m = match_app(name, self.phone.apps, self.memory.app_aliases())
        params = {"package": m.package} if m else {"name": name}
        try:
            res = await self.call(ctx, "app.open", params, origin=origin)
        except PhoneError as e:
            if e.code in ("target.not_found", "app.not_installed"):
                return Outcome(False, self._t(ctx, "app_not_found", name=name), code=e.code)
            raise
        self.memory.last["app"] = res.get("label") or (m.label if m else name)
        return Outcome(True, self._t(ctx, "app_opened", label=res.get("label") or (m.label if m else name)), res)

    async def alarm(self, ctx: TaskContext, hour: int, minute: int, day_hint: str | None, label: str | None,
                    days: list[int] | None = None, origin: str = "router") -> Outcome:
        params: dict = {"hour": hour, "minute": minute, "skipUi": True}
        if label:
            params["label"] = label[:80]
        if days:
            params["days"] = days
        res = await self.call(ctx, "intent.alarm", params, origin=origin)
        now = datetime.now()
        nxt = ClockTime(hour, minute, True, day_hint).next_occurrence(now)
        when = ""
        if not days:
            if nxt.date() == now.date():
                when = " (aaj)" if ctx.lang != "english" else " (today)"
                if day_hint == "tomorrow":
                    when += self._t(ctx, "alarm_today_warning")
            else:
                when = " (kal)" if ctx.lang != "english" else " (tomorrow)"
        return Outcome(True, self._t(ctx, "alarm", time=describe_clock(hour, minute), when=when), res)

    async def timer(self, ctx: TaskContext, seconds: int, label: str | None = None, origin: str = "router") -> Outcome:
        params: dict = {"seconds": seconds, "skipUi": True}
        if label:
            params["label"] = label[:80]
        res = await self.call(ctx, "intent.timer", params, origin=origin)
        return Outcome(True, self._t(ctx, "timer", duration=duration_text(seconds, ctx.lang)), res)

    async def search(self, ctx: TaskContext, engine: str, query: str, play: bool, origin: str = "router") -> Outcome:
        if engine == "music":
            engine = self.cfg.assistant.music_app
        res = await self.call(ctx, "intent.search", {"query": query, "engine": engine}, origin=origin)
        out = Outcome(True, self._t(ctx, "search", engine=_ENGINE_LABEL.get(engine, engine), query=query), res)
        if play and engine in ("youtube", "spotify"):
            out.followup_goal = f"Play '{query}' in {_ENGINE_LABEL[engine]}: the search results are already open, tap the most relevant result to start playing it."
            out.followup_hint = "Results should already be on screen; usually one tap on the first matching result is enough. Then call done."
        return out

    async def navigate(self, ctx: TaskContext, destination: str, origin: str = "router") -> Outcome:
        res = await self.call(ctx, "intent.navigate", {"destination": destination}, origin=origin)
        return Outcome(True, self._t(ctx, "navigate", destination=destination), res)

    async def status(self, ctx: TaskContext, what: str) -> Outcome:
        st = await self.phone.refresh_status()
        b = st.get("battery") or {}
        charging = self._t(ctx, "battery_charging") if b.get("charging") else ""
        text = self._t(ctx, "battery", level=b.get("level", "?"), charging=charging)
        if what == "all":
            fg = (st.get("foreground") or {}).get("label") or (st.get("foreground") or {}).get("package") or "?"
            vol = (st.get("volume") or {}).get("media") or {}
            extra = f" Media volume {vol.get('level', '?')}/{vol.get('max', '?')}, ringer {st.get('ringer', '?')}, screen pe {fg}."
            text += extra
        return Outcome(True, text, st)

    async def notifications(self, ctx: TaskContext, app: str | None, limit: int, origin: str = "router") -> Outcome:
        params: dict = {"limit": max(1, min(20, limit))}
        app_label = None
        if app:
            m = match_app(app, self.phone.apps, self.memory.app_aliases())
            if m:
                params["package"], app_label = m.package, m.label
            else:
                app_label = app
        res = await self.call(ctx, "notif.list", params, origin=origin)
        items = res.get("notifications") or []
        if app and "package" not in params:
            items = [n for n in items if app.lower() in (n.get("app") or "").lower()]
        if not items:
            return Outcome(True, self._t(ctx, "notif_none_app", app=app_label) if app_label else self._t(ctx, "notif_none"), res)
        parts = []
        for n in items[: min(limit, 3)]:
            line = f"{n.get('app') or ''}: {n.get('title') or ''}"
            if n.get("text"):
                line += f" — {n['text']}"
            parts.append(line.strip(": "))
        more = len(items) - len(parts)
        text = " | ".join(parts)
        if more > 0:
            text += f" (+{more} aur)" if ctx.lang != "english" else f" (+{more} more)"
        return Outcome(True, text, {"notifications": items})

    # ------------------------------------------------------------------ settings toggles
    async def toggle(self, ctx: TaskContext, setting: str, on: bool, origin: str = "router") -> Outcome:
        label = _TOGGLE_LABEL.get(setting, setting)
        state = ("on" if on else "off") if ctx.lang == "english" else ("on" if on else "band")
        if self.adb is not None and self.adb.enabled and self.adb.supports_toggle(setting):
            await self.adb.toggle(setting, on)
            return Outcome(True, self._t(ctx, "toggle_done", setting=label, state=state))
        await self.call(ctx, "device.settings", {"panel": _TOGGLE_PANEL[setting]}, origin=origin)
        target = None
        snap: dict = {}
        for _ in range(6):
            await asyncio.sleep(0.6)
            try:
                snap = await self.call(ctx, "ui.snapshot", {"maxElements": 120}, origin=origin)
            except PhoneError as e:
                if e.code == "permission.accessibility":
                    return Outcome(True, self._t(ctx, "toggle_panel", setting=label))
                raise
            target = find_toggle(snap, _TOGGLE_WORDS[setting])
            if target:
                break
        if not target:
            return Outcome(True, self._t(ctx, "toggle_panel", setting=label),
                           followup_goal=f"Turn {label} {'on' if on else 'off'} using the settings screen that is open.")
        if bool(target.get("checked")) == on:
            return Outcome(True, self._t(ctx, "toggle_already", setting=label, state=state))
        await self.call(ctx, "ui.tap", {"snapshotId": snap["snapshotId"], "elementId": target["id"]}, origin=origin)
        await asyncio.sleep(1.0)
        snap2 = await self.call(ctx, "ui.snapshot", {"maxElements": 120}, origin=origin)
        t2 = find_toggle(snap2, _TOGGLE_WORDS[setting])
        if t2 is not None and bool(t2.get("checked")) != on:
            return Outcome(False, self._t(ctx, "failed", reason=f"{label} toggle did not change"))
        return Outcome(True, self._t(ctx, "toggle_done", setting=label, state=state))

    # ------------------------------------------------------------------ contacts / external
    async def resolve_contact(self, ctx: TaskContext, who: str, origin: str) -> tuple[str, str] | Outcome:
        """-> (display name, E.164-ish number) or an Outcome (clarify / not found)."""
        who = who.strip()
        if re.fullmatch(r"\+?[\d\s()-]{6,20}", who):
            return who, normalize_number(who, self.cfg.assistant.default_country_code)
        alias = self.memory.contact_alias(who)
        query = who
        if alias:
            if alias.get("number"):
                return alias["contact_name"], normalize_number(alias["number"], self.cfg.assistant.default_country_code)
            query = alias["contact_name"]
        res = await self.call(ctx, "contacts.search", {"query": query, "limit": 6}, origin=origin)
        contacts = [c for c in (res.get("contacts") or []) if c.get("numbers")]
        if not contacts:
            if res.get("contacts"):
                return Outcome(False, self._t(ctx, "no_number", name=res["contacts"][0].get("name", who)), code="target.not_found")
            return Outcome(False, self._t(ctx, "contact_not_found", name=who), code="target.not_found")
        exact = [c for c in contacts if c["name"].strip().lower() == query.lower()]
        chosen = None
        if len(exact) == 1:
            chosen = exact[0]
        elif len(contacts) == 1:
            chosen = contacts[0]
        else:
            pool = exact or contacts
            names = [c["name"] for c in pool][:5]
            ans = await self.gate.ask(self._t(ctx, "contact_choose", name=who) + " " + " / ".join(names), kind="choose",
                                      options=names, task_id=ctx.task_id, source=ctx.source)
            if not ans:
                return Outcome(False, self._t(ctx, "no_answer"), code="clarify")
            chosen = next(c for c in pool if c["name"] == ans)
        nums = chosen["numbers"]
        mobile = [n for n in nums if "mobile" in (n.get("label") or "").lower()]
        number = (mobile or nums)[0]["number"]
        return chosen["name"], normalize_number(number, self.cfg.assistant.default_country_code)

    async def call_contact(self, ctx: TaskContext, who: str, *, deterministic: bool, origin: str = "router") -> Outcome:
        r = await self.resolve_contact(ctx, who, origin)
        if isinstance(r, Outcome):
            return r
        name, number = r
        refused = await self._confirm_external(ctx, self._t(ctx, "confirm_call", name=name, number=number), deterministic)
        if refused:
            return refused
        self.memory.note_contact(name, number)
        res = await self.call(ctx, "comm.call", {"number": number}, origin=origin, confirmed=True)
        key = "called" if res.get("mode") == "call" else "dialed"
        return Outcome(True, self._t(ctx, key, name=name), res)

    async def message(self, ctx: TaskContext, channel: str, who: str, body: str, *, deterministic: bool,
                      origin: str = "router") -> Outcome:
        body = body.strip()
        if not body:
            return Outcome(False, "Kya message bhejna hai?" if ctx.lang != "english" else "What should the message say?",
                           code="clarify")
        if channel in ("default", "", None):
            channel = self.cfg.assistant.default_message_channel
        r = await self.resolve_contact(ctx, who, origin)
        if isinstance(r, Outcome):
            return r
        name, number = r
        chan_label = "WhatsApp" if channel == "whatsapp" else "SMS"
        self.memory.note_contact(name, number)
        self.memory.note_message(body, channel)
        refused = await self._confirm_external(
            ctx, self._t(ctx, "confirm_message", name=name, channel=chan_label, body=body), deterministic)
        if refused:
            return refused
        if channel == "whatsapp":
            res = await self.call(ctx, "comm.whatsapp", {"number": number, "text": body}, origin=origin,
                                  confirmed=True, timeout=40)
            state = res.get("state")
            if state == "sent":
                return Outcome(True, self._t(ctx, "message_sent", name=name, channel=chan_label, body=body), res)
            if state == "composer":
                return Outcome(True, self._t(ctx, "message_composer", channel=chan_label), res)
            return Outcome(False, self._t(ctx, "message_uncertain"), res, uncertain=True, code="action.uncertain")
        res = await self.call(ctx, "comm.sms", {"number": number, "text": body}, origin=origin, confirmed=True)
        if res.get("mode") == "composer":
            return Outcome(True, self._t(ctx, "message_composer", channel=chan_label), res)
        return Outcome(True, self._t(ctx, "message_sent", name=name, channel=chan_label, body=body), res)


def find_toggle(snapshot: dict, words: list[str]) -> dict | None:
    """Find a switch/checkbox whose label (own text or same-row text) matches one of ``words``."""
    els = snapshot.get("elements") or []

    def label_of(e: dict) -> str:
        return " ".join(str(e.get(k) or "") for k in ("text", "desc")).lower()

    def matches(s: str) -> bool:
        return any(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", s) for w in words)

    checkables = [e for e in els if e.get("checked") is not None or "check" in (e.get("flags") or [])]
    for e in checkables:
        if matches(label_of(e)):
            return e
    for e in checkables:
        b = e.get("b") or [0, 0, 0, 0]
        cy = (b[1] + b[3]) / 2
        for t in els:
            if t is e:
                continue
            tb = t.get("b") or [0, 0, 0, 0]
            if abs((tb[1] + tb[3]) / 2 - cy) < 70 and matches(label_of(t)):
                return e
    return None
