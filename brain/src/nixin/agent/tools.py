"""Tools the phone agent (planner model) may call, and how each maps to phone methods.

The model never builds protocol messages: it picks one of these tools, the arguments
are validated here, element ids are checked against the latest snapshot, and only
then is a phone method called.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nixin.agent.screen import find_element


def _fn(name: str, desc: str, props: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required or [], "additionalProperties": False},
        },
    }


_ID = {"type": "integer", "description": "element id from SCREEN"}

PLANNER_TOOLS: list[dict] = [
    _fn("tap", "Tap an element.", {"id": _ID}, ["id"]),
    _fn("long_press", "Long-press an element.", {"id": _ID}, ["id"]),
    _fn("type_text", "Type into a text field (replaces its text). id optional = focused field.",
        {"text": {"type": "string"}, "id": _ID, "submit": {"type": "boolean", "description": "press enter/search after typing"}},
        ["text"]),
    _fn("scroll", "Scroll the screen or a list. down = reveal content below.",
        {"direction": {"type": "string", "enum": ["up", "down", "left", "right"]}, "id": _ID}, ["direction"]),
    _fn("press", "Press a system key.", {"key": {"type": "string", "enum": ["back", "home", "enter", "recents"]}}, ["key"]),
    _fn("open_app", "Launch an app by name (fastest way to start).", {"name": {"type": "string"}}, ["name"]),
    _fn("swipe", "Raw swipe in screen pixels.",
        {"x1": {"type": "integer"}, "y1": {"type": "integer"}, "x2": {"type": "integer"}, "y2": {"type": "integer"}},
        ["x1", "y1", "x2", "y2"]),
    _fn("tap_xy", "Tap raw screen coordinates (only when the element is not in SCREEN).",
        {"x": {"type": "integer"}, "y": {"type": "integer"}}, ["x", "y"]),
    _fn("wait", "Wait for the screen to load.", {"seconds": {"type": "number", "minimum": 0.5, "maximum": 5}}, ["seconds"]),
    _fn("look", "Take a screenshot and ask the vision model a question about it (use when SCREEN is empty/unclear).",
        {"question": {"type": "string"}}, ["question"]),
    _fn("send_message", "Send a WhatsApp/SMS message to a contact (verifies the recipient, asks the user).",
        {"to": {"type": "string"}, "text": {"type": "string"}, "channel": {"type": "string", "enum": ["whatsapp", "sms"]}},
        ["to", "text"]),
    _fn("call_contact", "Phone call a contact (asks the user first).", {"to": {"type": "string"}}, ["to"]),
    _fn("read_notifications", "Get recent notifications, optionally for one app.",
        {"app": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}}),
    _fn("ask_user", "Ask the user a short question when the goal is ambiguous.", {"question": {"type": "string"}}, ["question"]),
    _fn("done", "The goal is achieved. `answer` = information the user asked for (their language).",
        {"summary": {"type": "string"}, "answer": {"type": "string"}}, ["summary"]),
    _fn("fail", "Give up with a short reason (after trying alternatives).", {"reason": {"type": "string"}}, ["reason"]),
]
PLANNER_TOOL_NAMES = {t["function"]["name"] for t in PLANNER_TOOLS}
UI_TOOLS = {"tap", "long_press", "type_text", "scroll", "press", "swipe", "tap_xy", "open_app"}
TERMINAL_TOOLS = {"done", "fail"}


@dataclass
class ToolCheck:
    ok: bool
    error: str = ""


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def check_tool(name: str, args: dict, snapshot: dict | None, vision_ready: bool) -> ToolCheck:
    """Validate a proposed tool call against the latest snapshot. Errors are fed back to the model."""
    if name not in PLANNER_TOOL_NAMES:
        return ToolCheck(False, f"Unknown tool '{name}'. Use one of: {', '.join(sorted(PLANNER_TOOL_NAMES))}.")
    if name in ("tap", "long_press"):
        i = _int(args.get("id"))
        if i is None:
            return ToolCheck(False, f"{name} needs an integer id from SCREEN.")
        e = find_element(snapshot, i)
        if e is None:
            return ToolCheck(False, f"Element [{i}] is not on the current SCREEN. Pick an id from the list.")
        if "off" in (e.get("flags") or []):
            return ToolCheck(False, f"Element [{i}] is disabled.")
    if name == "type_text":
        if not isinstance(args.get("text"), str):
            return ToolCheck(False, "type_text needs text.")
        if args.get("id") is not None:
            e = find_element(snapshot, _int(args.get("id")) or -1)
            if e is None:
                return ToolCheck(False, f"Element [{args.get('id')}] is not on the current SCREEN.")
            if "pwd" in (e.get("flags") or []):
                return ToolCheck(False, "Refusing to type into a password field.")
    if name == "scroll" and args.get("direction") not in ("up", "down", "left", "right"):
        return ToolCheck(False, "scroll direction must be up/down/left/right.")
    if name == "press" and args.get("key") not in ("back", "home", "enter", "recents"):
        return ToolCheck(False, "press key must be back/home/enter/recents.")
    if name in ("swipe", "tap_xy"):
        keys = ("x1", "y1", "x2", "y2") if name == "swipe" else ("x", "y")
        w, h = (snapshot or {}).get("width", 4000), (snapshot or {}).get("height", 8000)
        for k in keys:
            v = _int(args.get(k))
            if v is None or v < 0 or v > (w if k.startswith("x") else h):
                return ToolCheck(False, f"{name}: {k} must be inside the screen ({w}x{h}).")
    if name == "look" and not vision_ready:
        return ToolCheck(False, "look() is unavailable (vision disabled). Work with SCREEN, scroll, or fail.")
    if name == "open_app" and not str(args.get("name", "")).strip():
        return ToolCheck(False, "open_app needs a name.")
    if name in ("send_message",) and not (args.get("to") and args.get("text")):
        return ToolCheck(False, "send_message needs to and text.")
    return ToolCheck(True)


def action_signature(name: str, args: dict) -> str:
    return name + ":" + ",".join(f"{k}={args[k]}" for k in sorted(args) if k != "summary")


def describe_call(name: str, args: dict) -> str:
    inner = ", ".join(f"{k}={str(v)[:40]!r}" if isinstance(v, str) else f"{k}={v}" for k, v in args.items())
    return f"{name}({inner})"
