"""Turn a ui.snapshot into compact text for the LLM (the #1 lever on free-tier token limits).

Snapshot element format (from the phone):
  {"id": 7, "role": "input", "text": "…", "desc": "…", "hint": "…", "res": "entry",
   "b": [l, t, r, b], "flags": ["click","edit","focus","scroll","long","sel","off","pwd"], "checked": true|false}
Rendered line:
  [7] input "Message" (focused) @540,2250
"""

from __future__ import annotations

import hashlib

_FLAG_TEXT = {"focus": "focused", "sel": "selected", "off": "disabled", "scroll": "scrollable", "pwd": "password"}


def _q(s: str, n: int = 70) -> str:
    s = " ".join(str(s).split())
    return (s[: n - 1] + "…") if len(s) > n else s


def element_label(e: dict) -> str:
    text, desc, hint = e.get("text"), e.get("desc"), e.get("hint")
    parts = []
    if text:
        parts.append(f'"{_q(text)}"')
    if desc and desc != text:
        parts.append(f'desc="{_q(desc, 50)}"')
    if hint and not text:
        parts.append(f'hint="{_q(hint, 40)}"')
    if not parts and e.get("res"):
        parts.append(f"#{e['res']}")
    return " ".join(parts)


def render_element(e: dict) -> str:
    flags = e.get("flags") or []
    bits = [f"[{e['id']}] {e.get('role', 'view')}"]
    label = element_label(e)
    if label:
        bits.append(label)
    marks = [_FLAG_TEXT[f] for f in flags if f in _FLAG_TEXT]
    if e.get("checked") is not None:
        marks.append("on" if e["checked"] else "off")
    if marks:
        bits.append("(" + ", ".join(marks) + ")")
    b = e.get("b")
    if b and len(b) == 4:
        bits.append(f"@{(b[0] + b[2]) // 2},{(b[1] + b[3]) // 2}")
    return " ".join(bits)


def render(snapshot: dict, max_chars: int = 4000) -> str:
    if not snapshot:
        return "(no screen)"
    head = f"App: {snapshot.get('app') or '?'} ({snapshot.get('package') or '?'})"
    if snapshot.get("title"):
        head += f" · title \"{_q(snapshot['title'], 60)}\""
    head += f" · screen {snapshot.get('width', '?')}x{snapshot.get('height', '?')}"
    if snapshot.get("keyboard"):
        head += " · keyboard open"
    lines = [head]
    used = len(head)
    els = snapshot.get("elements") or []
    shown = 0
    for e in els:
        line = render_element(e)
        if used + len(line) + 1 > max_chars:
            break
        lines.append(line)
        used += len(line) + 1
        shown += 1
    hidden = len(els) - shown
    if hidden > 0 or snapshot.get("truncated"):
        lines.append(f"… {hidden if hidden > 0 else 'more'} elements not shown (scroll to see more)")
    if not els:
        lines.append("(no readable elements — the app may draw its own UI; try look() or scroll)")
    return "\n".join(lines)


def screen_hash(snapshot: dict | None) -> str:
    if not snapshot:
        return ""
    h = hashlib.sha1()
    h.update(str(snapshot.get("package")).encode())
    for e in snapshot.get("elements") or []:
        h.update(f"{e.get('role')}|{e.get('text')}|{e.get('desc')}|{e.get('checked')}|{'focus' in (e.get('flags') or [])}".encode())
    return h.hexdigest()[:16]


def find_element(snapshot: dict | None, element_id: int) -> dict | None:
    for e in (snapshot or {}).get("elements") or []:
        if e.get("id") == element_id:
            return e
    return None
