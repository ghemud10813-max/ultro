"""Intent classifier (fast model): free-form command -> list of Intents.

Runs only when the deterministic router could not handle the command. One call,
usually ~1k tokens. Tool calls map 1:1 to router Intents so both paths share the
same executor (and the same safety checks).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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
        case "phone_task":
            return Intent("agent", {"goal": a["goal"]}, text)
        case "reply":
            return Intent("reply", {"text": a["text"]}, text)
        case "ask":
            return Intent("clarify", {"question": a["question"]}, text)
    return None


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
