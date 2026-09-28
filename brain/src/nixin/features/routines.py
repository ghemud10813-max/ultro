"""Routines: "when THIS happens, do THAT" — Nixin's proactive side.

Triggers
  time      every day / chosen weekdays at HH:MM       "har raat 11 baje phone silent kar dena"
  interval  every N minutes                            (dashboard)
  once      a single moment (reminders)                "10 minute baad yaad dilana ki chai"
  event     something happens on the phone             "jab battery 20% se kam ho to bata dena"
  phrase    you say a phrase (scenes / macros)         "good night" -> DND + brightness + pause music

Actions are ordinary Nixin commands (the same text you would say) plus:
  "say: <text>"     speak/announce (PC and/or phone)
  "notify: <text>"  phone notification + PC desktop notification
  "wait: <seconds>"
Placeholders filled from the event: {level} {app} {title} {text} {caller} {name} {time}
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from nixin.features.base import Feature, Intent, Outcome, TaskContext, tr
from nixin.router.normalize import clean

if TYPE_CHECKING:
    from nixin.app import NixinApp

EVENTS = (
    "battery_low", "battery_full", "charging", "unplugged", "notification", "call_incoming",
    "screen_on", "screen_off", "unlocked", "phone_connected", "phone_disconnected", "wifi_connected", "wifi_disconnected",
)


class Trigger(BaseModel):
    type: Literal["time", "interval", "once", "event", "phrase"]
    at: str | None = None  # "HH:MM" for time
    days: list[int] = Field(default_factory=list)  # ISO weekdays 1=Mon..7=Sun; empty = every day
    minutes: int | None = None  # interval
    when: float | None = None  # epoch seconds for once
    event: str | None = None
    below: int | None = None
    above: int | None = None
    app: str | None = None
    contains: str | None = None
    phrases: list[str] = Field(default_factory=list)

    def describe(self) -> str:
        t = self.type
        if t == "time":
            days = "" if not self.days else " (" + ",".join("MTWTFSS"[d - 1] for d in sorted(self.days)) + ")"
            return f"daily at {self.at}{days}"
        if t == "interval":
            return f"every {self.minutes} min"
        if t == "once":
            return "once at " + datetime.fromtimestamp(self.when or 0).strftime("%d %b %H:%M")
        if t == "phrase":
            return "when you say " + " / ".join(f'"{p}"' for p in self.phrases)
        bits = [self.event or "?"]
        if self.below is not None:
            bits.append(f"below {self.below}%")
        if self.above is not None:
            bits.append(f"≥{self.above}%")
        if self.app:
            bits.append(f"app={self.app}")
        if self.contains:
            bits.append(f'contains "{self.contains}"')
        return "on " + " ".join(bits)


class Routine(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    name: str
    enabled: bool = True
    trusted: bool = False  # may send messages/calls without asking
    trigger: Trigger
    actions: list[str]
    cooldown_minutes: float = 1.0
    last_run: float | None = None
    runs: int = 0
    builtin: bool = False
    created_at: float = Field(default_factory=time.time)
    delete_after_run: bool = False


def builtin_routines() -> list[Routine]:
    return [
        Routine(name="Good night", builtin=True, trigger=Trigger(type="phrase", phrases=[
            "good night", "shubh ratri", "so raha hoon", "so rahi hoon", "sone ja raha hoon", "night mode"]),
            actions=["dnd on karo", "brightness 15 percent", "gaana band karo", "say: Good night! DND on hai, subah milte hain."]),
        Routine(name="Good morning", builtin=True, trigger=Trigger(type="phrase", phrases=[
            "good morning", "subah ho gayi", "gm", "uth gaya", "uth gayi"]),
            actions=["dnd band karo", "briefing"]),
        Routine(name="Study mode", builtin=True, trigger=Trigger(type="phrase", phrases=["study mode", "padhai mode", "focus mode"]),
                actions=["dnd on karo", "gaana band karo", "say: Focus mode on. All the best!"]),
        Routine(name="Meeting mode", builtin=True, trigger=Trigger(type="phrase", phrases=["meeting mode", "meeting mein hoon"]),
                actions=["phone silent kar do", "say: Meeting mode — phone silent hai."]),
        Routine(name="Low battery alert", builtin=True, cooldown_minutes=60,
                trigger=Trigger(type="event", event="battery_low", below=20),
                actions=["say: Phone ki battery {level}% reh gayi hai, charger laga lo."]),
        Routine(name="Battery full alert", builtin=True, cooldown_minutes=60,
                trigger=Trigger(type="event", event="battery_full", above=100),
                actions=["say: Phone full charge ho gaya, charger nikal do."]),
    ]


_PLACEHOLDER = re.compile(r"\{(level|app|title|text|caller|name|time|ssid)\}")


def fill(template: str, data: dict) -> str:
    def rep(m: re.Match) -> str:
        k = m.group(1)
        if k == "time":
            return datetime.now().strftime("%I:%M %p").lstrip("0")
        v = data.get(k)
        return "" if v is None else str(v)

    return _PLACEHOLDER.sub(rep, template).strip()


class RoutineEngine(Feature):
    name = "routines"
    local = frozenset({"routine_add", "reminder", "routine_run", "routine_list", "routine_toggle", "routine_delete"})

    def __init__(self, app: NixinApp) -> None:
        super().__init__(app)
        self.routines: dict[str, Routine] = {}
        self._tasks: list[asyncio.Task] = []
        self._last_battery: int | None = None
        self._running: set[str] = set()
        self.load()

    # ------------------------------------------------------------------ storage
    def load(self) -> None:
        self.routines = {}
        for d in self.store.list_routines():
            try:
                r = Routine.model_validate(d)
                self.routines[r.id] = r
            except Exception:
                continue
        if not self.routines and self.app.cfg.routines.builtin and not self.store.get_setting("routines_seeded"):
            for r in builtin_routines():
                self.save(r)
            self.store.set_setting("routines_seeded", True)

    def save(self, r: Routine) -> Routine:
        self.routines[r.id] = r
        self.store.save_routine(r.id, r.model_dump())
        self.bus.emit("routines_changed")
        return r

    def delete(self, rid: str) -> bool:
        r = self.routines.pop(rid, None)
        self.store.delete_routine(rid)
        self.bus.emit("routines_changed")
        return r is not None

    def find(self, name: str) -> Routine | None:
        n = clean(name)
        for r in self.routines.values():
            if clean(r.name) == n:
                return r
        cands = [r for r in self.routines.values() if n and (n in clean(r.name) or clean(r.name) in n)]
        return cands[0] if len(cands) == 1 else None

    def list(self) -> list[Routine]:
        return sorted(self.routines.values(), key=lambda r: (not r.enabled, r.name.lower()))

    def phrases(self) -> list[dict]:
        return [{"name": r.name, "phrase": r.trigger.phrases[0]} for r in self.list()
                if r.enabled and r.trigger.type == "phrase" and r.trigger.phrases]

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        if self.cfg.routines.enabled:
            self._tasks = [asyncio.create_task(self._clock()), asyncio.create_task(self._events())]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()

    # ------------------------------------------------------------------ matching
    def match_phrase(self, text: str) -> Routine | None:
        c = re.sub(r"\b(?:nixin|please|plz|yaar|bhai)\b", " ", clean(text))
        c = re.sub(r"\s+", " ", c).strip()
        if not c:
            return None
        for r in self.routines.values():
            if not r.enabled or r.trigger.type != "phrase":
                continue
            for p in r.trigger.phrases:
                pc = clean(p)
                if c == pc or c in (pc + " karo", pc + " on karo", pc + " chalao", pc + " on", pc + " routine"):
                    return r
        return None

    def due_by_clock(self, now: datetime) -> list[Routine]:
        due: list[Routine] = []
        ts = now.timestamp()
        for r in self.routines.values():
            if not r.enabled:
                continue
            t = r.trigger
            if t.type == "time" and t.at:
                if now.strftime("%H:%M") == t.at and (not t.days or now.isoweekday() in t.days):
                    if not r.last_run or ts - r.last_run > 90:
                        due.append(r)
            elif t.type == "interval" and t.minutes:
                base = r.last_run or r.created_at
                if ts - base >= t.minutes * 60:
                    due.append(r)
            elif t.type == "once" and t.when and ts >= t.when and not r.last_run:
                due.append(r)
        return due

    def match_event(self, name: str, data: dict) -> list[tuple[Routine, dict]]:
        """Translate a raw phone event into routine events and return (routine, payload) pairs."""
        fired: list[tuple[str, dict]] = []
        if name == "battery":
            level = data.get("level")
            charging = bool(data.get("charging"))
            prev = self._last_battery
            if isinstance(level, int):
                self._last_battery = level
                fired.append(("_battery", {"level": level, "charging": charging, "prev": prev}))
        elif name == "power":
            fired.append(("charging" if data.get("plugged") else "unplugged", data))
        elif name == "screen":
            state = data.get("state")
            fired.append({"on": ("screen_on", data), "off": ("screen_off", data), "unlocked": ("unlocked", data)}.get(
                state, ("_", data)))
        elif name == "network":
            fired.append(("wifi_connected" if data.get("wifi") else "wifi_disconnected", data))
        elif name in ("notification", "call_incoming", "phone_connected", "phone_disconnected"):
            fired.append((name, data))

        out: list[tuple[Routine, dict]] = []
        for ev, payload in fired:
            for r in self.routines.values():
                t = r.trigger
                if not r.enabled or t.type != "event":
                    continue
                if ev == "_battery":
                    lvl, prev = payload["level"], payload["prev"]
                    if t.event == "battery_low":
                        limit = t.below if t.below is not None else 20
                        if lvl <= limit and not payload["charging"] and (prev is None or prev > limit):
                            out.append((r, payload))
                    elif t.event == "battery_full":
                        limit = t.above if t.above is not None else 100
                        if lvl >= limit and payload["charging"] and (prev is None or prev < limit):
                            out.append((r, payload))
                    continue
                if t.event != ev:
                    continue
                if ev == "notification":
                    app = (payload.get("app") or "") + " " + (payload.get("package") or "")
                    blob = f"{payload.get('title') or ''} {payload.get('text') or ''}"
                    if t.app and t.app.lower() not in app.lower():
                        continue
                    if t.contains and t.contains.lower() not in blob.lower():
                        continue
                elif ev == "call_incoming":
                    if t.contains and t.contains.lower() not in str(payload.get("caller") or "").lower():
                        continue
                elif ev == "wifi_connected" and t.contains:
                    if t.contains.lower() not in str(payload.get("ssid") or "").lower():
                        continue
                out.append((r, payload))
        return out

    # ------------------------------------------------------------------ loops
    async def _clock(self) -> None:
        while True:
            try:
                for r in self.due_by_clock(datetime.now()):
                    self.fire(r, {}, "time")
            except Exception as e:  # noqa: BLE001
                self.bus.emit("log", level="error", msg=f"Routine clock error: {e!r}")
            await asyncio.sleep(15)

    async def _events(self) -> None:
        q = self.bus.subscribe()
        try:
            while True:
                ev = await q.get()
                if ev["type"] != "device_event":
                    continue
                for r, payload in self.match_event(ev.get("name", ""), ev.get("data") or {}):
                    self.fire(r, payload, ev.get("name", "event"))
        finally:
            self.bus.unsubscribe(q)

    # ------------------------------------------------------------------ execution
    def fire(self, r: Routine, data: dict, reason: str) -> bool:
        now = time.time()
        if r.id in self._running:
            return False
        if r.last_run and now - r.last_run < r.cooldown_minutes * 60 and r.trigger.type not in ("phrase",):
            return False
        asyncio.create_task(self.run(r, data, reason))
        return True

    async def run(self, r: Routine, data: dict | None = None, reason: str = "manual", *,
                  collect: bool = False) -> list[str]:
        """Run a routine's actions in order. ``collect`` (scenes you say out loud): return the replies so the
        caller speaks one combined answer instead of announcing each step."""
        data = data or {}
        self._running.add(r.id)
        r.last_run = time.time()
        r.runs += 1
        if r.id in self.routines:
            self.save(r)
        self.bus.emit("routine", id=r.id, name=r.name, status="running", reason=reason)
        spoken: list[str] = []
        replies: list[str] = []
        notified = False
        brain = self.app.brain
        try:
            for raw in r.actions:
                action = fill(raw, {**data, "name": r.name})
                low = action.lower()
                if low.startswith("say:"):
                    msg = action[4:].strip()
                    if collect:
                        spoken.append(msg)
                    else:
                        await brain.announce(msg)
                        spoken.append(msg)
                elif low.startswith("notify:"):
                    msg = action[7:].strip()
                    await brain.notify(r.name, msg)
                    notified = True
                    if collect:
                        spoken.append(msg)
                elif low.startswith("wait:"):
                    try:
                        await asyncio.sleep(min(600.0, float(action[5:].strip())))
                    except ValueError:
                        pass
                elif action:
                    reply = await brain.handle(action, source="routine", queue=True, quiet=True, trusted=r.trusted,
                                               event=data)
                    if reply:
                        replies.append(reply)
            self.bus.emit("routine", id=r.id, name=r.name, status="done", reason=reason, replies=replies + spoken)
            if not collect and not spoken and not notified and replies:
                await brain.post(f"⏰ {r.name}: " + " ".join(replies))
        except Exception as e:  # noqa: BLE001
            self.bus.emit("routine", id=r.id, name=r.name, status="failed", reason=reason, error=repr(e))
        finally:
            self._running.discard(r.id)
            if (r.delete_after_run or r.trigger.type == "once") and r.id in self.routines:
                self.delete(r.id)
        return spoken if (collect and spoken) else replies

    # ------------------------------------------------------------------ intents (voice-created routines)
    def handlers(self):
        return {"routine_add": self.add_intent, "reminder": self.reminder_intent, "routine_run": self.run_intent,
                "routine_list": self.list_intent, "routine_toggle": self.toggle_intent, "routine_delete": self.delete_intent}

    async def add_intent(self, intent: Intent, ctx: TaskContext, *, deterministic: bool = True, origin: str = "router") -> Outcome:
        p = intent.params
        trig = Trigger.model_validate(p["trigger"])
        actions = [a for a in (p.get("actions") or []) if str(a).strip()]
        if not actions:
            return Outcome(False, tr(ctx, "Routine mein kya karna hai?", "What should the routine do?"), code="clarify")
        name = (p.get("name") or "").strip() or _auto_name(trig, actions)
        r = self.save(Routine(name=name[:60], trigger=trig, actions=actions, trusted=False,
                              cooldown_minutes=float(p.get("cooldown") or (30 if trig.type == "event" else 1))))
        return Outcome(True, tr(ctx, f"Routine bana di — {r.trigger.describe()}: {'; '.join(r.actions)}. Dashboard pe edit kar sakte ho.",
                                f"Routine created — {r.trigger.describe()}: {'; '.join(r.actions)}. You can edit it on the dashboard."),
                       {"routine": r.model_dump()})

    async def reminder_intent(self, intent: Intent, ctx: TaskContext, *, deterministic: bool = True,
                              origin: str = "router") -> Outcome:
        p = intent.params
        text = (p.get("text") or "").strip() or tr(ctx, "Reminder", "Reminder")
        when = float(p["when"])
        r = self.save(Routine(name=f"⏰ {text[:50]}", trigger=Trigger(type="once", when=when),
                              actions=[f"notify: {text}", "say: " + tr(ctx, f"Yaad dila raha hoon: {text}", f"Reminder: {text}")],
                              cooldown_minutes=0))
        dt = datetime.fromtimestamp(when)
        now = datetime.now()
        at = dt.strftime("%I:%M %p").lstrip("0")
        day = "" if dt.date() == now.date() else tr(ctx, " kal", " tomorrow") if (dt.date() - now.date()).days == 1 \
            else " " + dt.strftime("%d %b")
        return Outcome(True, tr(ctx, f"Theek hai,{day} {at} pe yaad dila dunga: {text}",
                                f"Okay, I'll remind you{day} at {at}: {text}"), {"routine": r.id})

    async def run_intent(self, intent: Intent, ctx: TaskContext, *, deterministic: bool = True, origin: str = "router") -> Outcome:
        r = self.find(intent.params.get("name") or "")
        if r is None:
            return Outcome(False, tr(ctx, "Aisi koi routine nahi mili.", "I couldn't find that routine."))
        replies = await self.run(r, {}, "manual", collect=True)
        return Outcome(True, " ".join(replies) or tr(ctx, f"'{r.name}' chala di.", f"Ran '{r.name}'."))

    async def list_intent(self, intent: Intent, ctx: TaskContext, *, deterministic: bool = True, origin: str = "router") -> Outcome:
        only = intent.params.get("only")
        items = [r for r in self.list() if (only != "reminders" or r.trigger.type == "once")]
        if not items:
            return Outcome(True, tr(ctx, "Koi routine/reminder nahi hai.", "No routines or reminders."))
        parts = [f"{r.name}{'' if r.enabled else ' (off)'} — {r.trigger.describe()}" for r in items[:8]]
        more = len(items) - len(parts)
        text = " | ".join(parts) + (f" (+{more})" if more > 0 else "")
        return Outcome(True, text, {"routines": [r.model_dump() for r in items]})

    async def toggle_intent(self, intent: Intent, ctx: TaskContext, *, deterministic: bool = True, origin: str = "router") -> Outcome:
        r = self.find(intent.params.get("name") or "")
        if r is None:
            return Outcome(False, tr(ctx, "Aisi koi routine nahi mili.", "I couldn't find that routine."))
        r.enabled = bool(intent.params.get("on"))
        self.save(r)
        return Outcome(True, tr(ctx, f"'{r.name}' {'on' if r.enabled else 'band'} kar di.",
                                f"'{r.name}' turned {'on' if r.enabled else 'off'}."))

    async def delete_intent(self, intent: Intent, ctx: TaskContext, *, deterministic: bool = True, origin: str = "router") -> Outcome:
        r = self.find(intent.params.get("name") or "")
        if r is None:
            return Outcome(False, tr(ctx, "Aisi koi routine nahi mili.", "I couldn't find that routine."))
        self.delete(r.id)
        return Outcome(True, tr(ctx, f"'{r.name}' delete kar di.", f"Deleted '{r.name}'."))


def _auto_name(t: Trigger, actions: list[str]) -> str:
    first = re.sub(r"^(?:say|notify):\s*", "", actions[0])[:30]
    if t.type == "time":
        return f"{t.at} — {first}"
    if t.type == "event":
        return f"{t.event} — {first}"
    if t.type == "phrase" and t.phrases:
        return t.phrases[0].title()
    return first
