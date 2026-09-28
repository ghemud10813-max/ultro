"""Intent classifier (fast model): free-form command -> list of Intents.

Runs only when the deterministic router could not handle the command. One call,
usually ~1k tokens. Tool calls map 1:1 to router Intents so both paths share the
same executor (and the same safety checks).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from nixin.agent import prompts
from nixin.agent.tools import _fn
from nixin.core.memory import Memory
from nixin.link.phone import PhoneLink
from nixin.llm.gateway import Gateway
from nixin.router.router import Intent

CLASSIFIER_TOOLS: list[dict] = [
    _fn("set_volume", "Change volume.", {
        "action": {"type": "string", "enum": ["up", "down", "set", "mute", "unmute", "max"]},
        "stream": {"type": "string", "enum": ["media", "ring", "alarm", "notification", "call"]},
        "percent": {"type": "integer", "minimum": 0, "maximum": 100},
        "steps": {"type": "integer", "minimum": 1, "maximum": 15}}, ["action"]),
    _fn("torch", "Flashlight on/off.", {"on": {"type": "boolean"}}, ["on"]),
    _fn("brightness", "Screen brightness.", {"action": {"type": "string", "enum": ["set", "up", "down", "auto"]},
                                             "percent": {"type": "integer", "minimum": 0, "maximum": 100}}, ["action"]),
    _fn("ringer", "Ringer mode.", {"mode": {"type": "string", "enum": ["normal", "vibrate", "silent"]}}, ["mode"]),
    _fn("dnd", "Do Not Disturb.", {"on": {"type": "boolean"}}, ["on"]),
    _fn("toggle_setting", "Turn a connectivity setting on/off.", {
        "setting": {"type": "string", "enum": ["wifi", "bluetooth", "mobile_data", "hotspot", "location", "airplane", "nfc"]},
        "on": {"type": "boolean"}}, ["setting", "on"]),
    _fn("system", "System navigation.", {"action": {"type": "string", "enum": [
        "back", "home", "recents", "notifications", "quick_settings", "lock_screen", "screenshot"]}}, ["action"]),
    _fn("open_app", "Open an app.", {"name": {"type": "string"}}, ["name"]),
    _fn("send_message", "Send a message. text = exactly what the user wants sent.", {
        "to": {"type": "string", "description": "contact name/nickname or number"},
        "text": {"type": "string"},
        "channel": {"type": "string", "enum": ["whatsapp", "sms", "default"]}}, ["to", "text"]),
    _fn("call_contact", "Phone call.", {"to": {"type": "string"}}, ["to"]),
    _fn("set_alarm", "Alarm at a local time (24h). days: repeat 1=Sun..7=Sat.", {
        "hour": {"type": "integer", "minimum": 0, "maximum": 23}, "minute": {"type": "integer", "minimum": 0, "maximum": 59},
        "label": {"type": "string"}, "days": {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": 7}}},
        ["hour", "minute"]),
    _fn("set_timer", "Countdown timer.", {"seconds": {"type": "integer", "minimum": 1}, "label": {"type": "string"}}, ["seconds"]),
    _fn("media", "Media playback control.", {"action": {"type": "string", "enum": ["play", "pause", "next", "previous", "stop"]}}, ["action"]),
    _fn("search", "Search web/YouTube/Play Store/Maps/Spotify. play=true to start playing the top result.", {
        "engine": {"type": "string", "enum": ["web", "youtube", "playstore", "maps", "spotify", "music"]},
        "query": {"type": "string"}, "play": {"type": "boolean"}}, ["engine", "query"]),
    _fn("navigate", "Google Maps navigation.", {"destination": {"type": "string"}}, ["destination"]),
    _fn("read_notifications", "Read recent notifications (optionally one app).", {
        "app": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}}),
    _fn("device_status", "Battery / phone status.", {"what": {"type": "string", "enum": ["battery", "all"]}}),
    _fn("remember", "Remember a fact the user tells you.", {"fact": {"type": "string"}}, ["fact"]),
    _fn("set_nickname", "Save a contact nickname (e.g. 'bhai' = 'Rohan Sharma').", {
        "alias": {"type": "string"}, "contact_name": {"type": "string"}}, ["alias", "contact_name"]),
    _fn("pc", "Control the user's PC/laptop (not the phone).", {
        "action": {"type": "string", "enum": ["lock", "sleep", "shutdown", "restart", "cancel_shutdown", "volume", "media", "open",
                                              "search", "screenshot", "type", "status", "clipboard_to_phone", "clipboard_from_phone"]},
        "target": {"type": "string", "description": "app/site to open"}, "query": {"type": "string"},
        "text": {"type": "string", "description": "text to type"},
        "mode": {"type": "string", "enum": ["up", "down", "set", "mute", "unmute", "max", "toggle", "next", "previous"]},
        "percent": {"type": "integer", "minimum": 0, "maximum": 100}}, ["action"]),
    _fn("weather", "Weather now/today/tomorrow. city empty = user's location.", {
        "city": {"type": "string"}, "when": {"type": "string", "enum": ["now", "today", "tomorrow"]},
        "rain": {"type": "boolean", "description": "the user asks specifically about rain"}}),
    _fn("briefing", "Daily briefing: time, weather, battery, notifications, screen time, reminders.", {}),
    _fn("reminder", "Remind the user later (spoken + notification). Give minutes_from_now OR hour+minute.", {
        "text": {"type": "string"}, "minutes_from_now": {"type": "integer", "minimum": 1},
        "hour": {"type": "integer", "minimum": 0, "maximum": 23}, "minute": {"type": "integer", "minimum": 0, "maximum": 59},
        "tomorrow": {"type": "boolean"}}, ["text"]),
    _fn("create_routine", "Automation: at a daily time (at=HH:MM, days 1=Mon..7=Sun) or on a phone event, run commands. "
        "actions = Nixin commands in the user's words, or 'say: <text>' to announce (placeholders {level} {title} {app} {text} {caller}).", {
        "name": {"type": "string"}, "at": {"type": "string", "pattern": "^\\d{2}:\\d{2}$"},
        "days": {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": 7}},
        "event": {"type": "string", "enum": ["battery_low", "battery_full", "charging", "unplugged", "notification", "call_incoming",
                                             "unlocked", "wifi_connected", "wifi_disconnected", "phone_connected"]},
        "below": {"type": "integer"}, "contains": {"type": "string", "description": "sender/caller name filter"},
        "app": {"type": "string"}, "actions": {"type": "array", "items": {"type": "string"}}}, ["actions"]),
    _fn("phone_extra", "Find/ring the phone, its location, call control, now playing, screen time, device info, system settings.", {
        "action": {"type": "string", "enum": ["find_phone", "stop_ringing", "location", "answer_call", "end_call", "speaker_on",
                                              "speaker_off", "mute_mic", "unmute_mic", "now_playing", "screen_time_today",
                                              "screen_time_yesterday", "screen_time_week", "storage", "device_info",
                                              "auto_rotate_on", "auto_rotate_off", "screen_timeout"]},
        "seconds": {"type": "integer", "description": "screen_timeout value"}}, ["action"]),
    _fn("notification_action", "Reply to / summarise / clear / open notifications. reply uses the notification's reply action.", {
        "action": {"type": "string", "enum": ["reply", "summarize", "clear", "open"]},
        "who": {"type": "string"}, "app": {"type": "string"}, "text": {"type": "string", "description": "reply text, exactly"}},
        ["action"]),
    _fn("read_screen", "Read the phone screen aloud, summarise it, or answer a question about what is on it.", {
        "mode": {"type": "string", "enum": ["read", "summary", "ask"]}, "question": {"type": "string"}}, ["mode"]),
    _fn("skill", "Teach mode: learn a task by watching the user, save/cancel the recording, run/list learned skills.", {
        "action": {"type": "string", "enum": ["teach", "save", "cancel", "run", "list"]}, "name": {"type": "string"},
        "arg": {"type": "string", "description": "text to type when running"}}, ["action"]),
    _fn("phone_task", "Multi-step task that needs operating app screens. goal = complete English instruction.", {
        "goal": {"type": "string"}}, ["goal"]),
    _fn("reply", "Answer/chat without touching the phone.", {"text": {"type": "string"}}, ["text"]),
    _fn("ask", "Ask the user one clarifying question.", {"question": {"type": "string"}}, ["question"]),
]


@dataclass
class Classification:
    intents: list[Intent]
    model: str
    raw: str = ""


def tool_to_intent(name: str, a: dict, text: str) -> Intent | None:
    def ph(method: str, params: dict) -> Intent:
        return Intent("phone", {"method": method, "params": {k: v for k, v in params.items() if v is not None}}, text)

    match name:
        case "set_volume":
            p = {"action": a.get("action"), "stream": a.get("stream") or "media"}
            if p["action"] == "set":
                p["percent"] = int(a.get("percent") if a.get("percent") is not None else 50)
            if p["action"] in ("up", "down"):
                p["steps"] = int(a.get("steps") or 2)
            return ph("device.volume", p)
        case "torch":
            return ph("device.torch", {"on": bool(a.get("on", True))})
        case "brightness":
            p = {"action": a.get("action") or "set"}
            if p["action"] == "set":
                p["percent"] = int(a.get("percent") if a.get("percent") is not None else 50)
            return ph("device.brightness", p)
        case "ringer":
            return ph("device.ringer", {"mode": a.get("mode") or "normal"})
        case "dnd":
            return ph("device.dnd", {"on": bool(a.get("on", True))})
        case "toggle_setting":
            return Intent("toggle", {"setting": a["setting"], "on": bool(a.get("on", True))}, text)
        case "system":
            return ph("device.global", {"action": a["action"]})
        case "open_app":
            return Intent("open_app", {"name": a["name"]}, text)
        case "send_message":
            return Intent("message", {"channel": a.get("channel") or "default", "who": a["to"], "body": a["text"]}, text)
        case "call_contact":
            return Intent("call", {"who": a["to"]}, text)
        case "set_alarm":
            return Intent("alarm", {"hour": int(a["hour"]), "minute": int(a["minute"]), "label": a.get("label"),
                                    "days": a.get("days"), "day_hint": None}, text)
        case "set_timer":
            return Intent("timer", {"seconds": int(a["seconds"]), "label": a.get("label")}, text)
        case "media":
            return ph("media.control", {"action": a["action"]})
        case "search":
            return Intent("search", {"engine": a.get("engine") or "web", "query": a["query"], "play": bool(a.get("play"))}, text)
        case "navigate":
            return Intent("navigate", {"destination": a["destination"]}, text)
        case "read_notifications":
            return Intent("notifications", {"app": a.get("app"), "limit": int(a.get("limit") or 3)}, text)
        case "device_status":
            return Intent("status", {"what": a.get("what") or "battery"}, text)
        case "remember":
            return Intent("remember", {"fact": a["fact"]}, text)
        case "set_nickname":
            return Intent("alias", {"alias": a["alias"], "name": a["contact_name"]}, text)
        case "pc":
            p = {k: a[k] for k in ("action", "target", "query", "text", "mode", "percent") if a.get(k) is not None}
            return Intent("pc", p, text)
        case "weather":
            return Intent("weather", {"city": a.get("city") or None, "when": a.get("when") or "now",
                                      "question": "rain" if a.get("rain") else None}, text)
        case "briefing":
            return Intent("briefing", {}, text)
        case "reminder":
            now = datetime.now()
            if a.get("minutes_from_now"):
                when = now + timedelta(minutes=int(a["minutes_from_now"]))
            elif a.get("hour") is not None:
                when = now.replace(hour=int(a["hour"]), minute=int(a.get("minute") or 0), second=0, microsecond=0)
                if a.get("tomorrow") or when <= now:
                    when += timedelta(days=1)
            else:
                return Intent("clarify", {"question": "Kab yaad dilaun?"}, text)
            return Intent("reminder", {"text": a["text"], "when": when.timestamp()}, text)
        case "create_routine":
            if a.get("event"):
                trig = {"type": "event", "event": a["event"], **{k: a[k] for k in ("below", "contains", "app") if a.get(k)}}
            elif a.get("at"):
                trig = {"type": "time", "at": a["at"], "days": a.get("days") or []}
            else:
                return Intent("clarify", {"question": "Kab chalana hai — kis time ya kis event pe?"}, text)
            return Intent("routine_add", {"name": a.get("name") or "", "trigger": trig, "actions": list(a["actions"])}, text)
        case "phone_extra":
            return _extra_intent(a, text)
        case "notification_action":
            kind = {"reply": "notif_reply", "summarize": "notif_summary", "clear": "notif_clear", "open": "notif_open"}[a["action"]]
            return Intent(kind, {k: a.get(k) for k in ("who", "app", "text")}, text)
        case "read_screen":
            return Intent("screen_read", {"mode": a.get("mode") or "summary", "question": a.get("question")}, text)
        case "skill":
            kind = {"teach": "skill_teach", "save": "skill_save", "cancel": "skill_cancel", "run": "skill_run",
                    "list": "skill_list"}[a["action"]]
            return Intent(kind, {"name": a.get("name") or "", "arg": a.get("arg")}, text)
        case "phone_task":
            return Intent("agent", {"goal": a["goal"]}, text)
        case "reply":
            return Intent("reply", {"text": a["text"]}, text)
        case "ask":
            return Intent("clarify", {"question": a["question"]}, text)
    return None


def _extra_intent(a: dict, text: str) -> Intent:
    act = a["action"]
    simple = {
        "find_phone": ("find_phone", {}), "stop_ringing": ("find_phone", {"stop": True}), "location": ("locate_phone", {}),
        "answer_call": ("call_control", {"action": "answer"}), "end_call": ("call_control", {"action": "end"}),
        "speaker_on": ("call_control", {"action": "speaker_on"}), "speaker_off": ("call_control", {"action": "speaker_off"}),
        "mute_mic": ("call_control", {"action": "mute"}), "unmute_mic": ("call_control", {"action": "unmute"}),
        "now_playing": ("now_playing", {}), "screen_time_today": ("usage", {"period": "today"}),
        "screen_time_yesterday": ("usage", {"period": "yesterday"}), "screen_time_week": ("usage", {"period": "week"}),
        "storage": ("device_info", {"what": "storage"}), "device_info": ("device_info", {"what": "all"}),
        "auto_rotate_on": ("device_setting", {"name": "auto_rotate", "value": True}),
        "auto_rotate_off": ("device_setting", {"name": "auto_rotate", "value": False}),
    }
    if act == "screen_timeout":
        return Intent("device_setting", {"name": "screen_timeout", "value": max(15, min(1800, int(a.get("seconds") or 60)))}, text)
    kind, params = simple[act]
    return Intent(kind, dict(params), text)


class Classifier:
    def __init__(self, gateway: Gateway, memory: Memory, phone: PhoneLink, history_turns: int = 6) -> None:
        self.gw = gateway
        self.memory = memory
        self.phone = phone
        self.history_turns = history_turns

    def _phone_line(self) -> str:
        if not self.phone.connected:
            return "not connected"
        fg = (self.phone.status.get("foreground") or {})
        return f"connected, foreground app: {fg.get('label') or fg.get('package') or 'unknown'}"

    async def classify(self, text: str, deadline: float | None = None) -> Classification:
        system = prompts.CLASSIFIER_SYSTEM.format(now=datetime.now().strftime("%A %d %B %Y, %H:%M"), phone=self._phone_line())
        mem = self.memory.prompt_block(text, self.history_turns)
        user = (mem + "\n\n" if mem else "") + f"User command: {text}"
        res = await self.gw.complete("classifier", [{"role": "system", "content": system}, {"role": "user", "content": user}],
                                     tools=CLASSIFIER_TOOLS, tool_choice="required", deadline=deadline)
        intents: list[Intent] = []
        for tc in res.tool_calls[:5]:
            try:
                it = tool_to_intent(tc.name, tc.arguments, text)
            except (KeyError, TypeError, ValueError):
                it = None
            if it is not None:
                intents.append(it)
        if not intents and res.content:
            intents.append(Intent("reply", {"text": res.content.strip()[:600]}, text))
        return Classification(intents, res.candidate, res.content)
