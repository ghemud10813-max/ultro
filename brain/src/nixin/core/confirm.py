"""Confirmation / clarification gate.

When Nixin needs a yes/no or a choice from you it asks on every channel at once
(console, dashboard, phone dialog, and by voice if you spoke the command); the first
answer wins. No answer before the timeout means "no".
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from nixin.core.events import EventBus

YES = re.compile(r"^\s*(?:haan+|ha+n?|han|yes|yeah|yep|yup|ok|okay|theek hai|thik hai|thik|theek|kar do|kardo|bhej do|bhejo|"
                 r"confirm|sure|ji|haan ji|haanji|ha ji|hmm+|y|go|go ahead|send|call|chalo|done|do it|han bhai|bilkul|zaroor)\b", re.I)
NO = re.compile(r"^\s*(?:nahi+n?|nai|na|no|nope|nah|mat|mat karo|cancel|ruk|ruko|rehne do|rahne do|chhodo|chodo|stop|n|galat|wrong)\b", re.I)


def parse_yes_no(text: str) -> str | None:
    if NO.match(text or ""):
        return "no"
    if YES.match(text or ""):
        return "yes"
    return None


@dataclass
class Ask:
    id: str
    kind: str  # confirm | choose | input
    text: str
    options: list[str]
    task_id: str | None
    source: str
    future: asyncio.Future = field(repr=False, default=None)  # type: ignore[assignment]


PhoneAsk = Callable[[dict], Awaitable[bool]]
Speak = Callable[[str], Awaitable[None]]
VoiceListen = Callable[[float], Awaitable[str | None]]


class ConfirmationGate:
    def __init__(self, bus: EventBus, timeout: float = 30.0) -> None:
        self.bus = bus
        self.timeout = timeout
        self.pending: dict[str, Ask] = {}
        self.phone_ask: PhoneAsk | None = None  # set by app: sends {"t":"ask"} to the phone
        self.speak: Speak | None = None  # set by app when TTS is available
        self.voice_listen: VoiceListen | None = None  # set by app when a mic is available

    @property
    def current(self) -> Ask | None:
        return next(iter(self.pending.values()), None)

    async def ask(self, text: str, *, kind: str = "confirm", options: list[str] | None = None,
                  task_id: str | None = None, source: str = "typed", timeout: float | None = None) -> str | None:
        """Returns "yes"/"no" for confirm, the chosen option for choose, free text for input, None on timeout."""
        a = Ask(str(uuid.uuid4()), kind, text, options or [], task_id, source)
        a.future = asyncio.get_running_loop().create_future()
        self.pending[a.id] = a
        self.bus.emit("ask", id=a.id, kind=kind, text=text, options=a.options, taskId=task_id)
        timeout = timeout or self.timeout

        side: list[asyncio.Task] = []
        if self.phone_ask:
            side.append(asyncio.create_task(self.phone_ask({
                "t": "ask", "id": a.id, "kind": kind, "text": text, "options": a.options,
                "timeoutSec": int(timeout), "taskId": task_id,
            })))
        if source in ("voice", "wake_word") and self.speak:
            side.append(asyncio.create_task(self._voice_round(a, timeout)))
        try:
            return await asyncio.wait_for(asyncio.shield(a.future), timeout)
        except TimeoutError:
            return None
        finally:
            self.pending.pop(a.id, None)
            for t in side:
                t.cancel()
            self.bus.emit("ask_closed", id=a.id, value=a.future.result() if a.future.done() and not a.future.cancelled() else None)

    async def _voice_round(self, a: Ask, timeout: float) -> None:
        try:
            await self.speak(a.text)  # type: ignore[misc]
            if self.voice_listen:
                heard = await self.voice_listen(min(8.0, timeout))
                if heard:
                    self.answer(a.id, heard)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    def answer(self, ask_id: str | None, value: str) -> bool:
        """Deliver an answer from any channel. ``ask_id=None`` answers the oldest pending ask."""
        a = self.pending.get(ask_id) if ask_id else self.current
        if a is None or a.future.done():
            return False
        v = (value or "").strip()
        if a.kind == "confirm":
            yn = parse_yes_no(v)
            if yn is None:
                return False
            a.future.set_result(yn)
        elif a.kind == "choose":
            choice = _pick_option(v, a.options)
            if choice is None:
                if parse_yes_no(v) == "no":
                    a.future.set_result(None)
                    return True
                return False
            a.future.set_result(choice)
        else:
            a.future.set_result(v)
        return True

    def cancel_all(self) -> None:
        for a in list(self.pending.values()):
            if not a.future.done():
                a.future.set_result(None)


def _pick_option(value: str, options: list[str]) -> str | None:
    v = value.strip().lower()
    if not v:
        return None
    ordinals = {"1": 0, "pehla": 0, "pehle": 0, "first": 0, "ek": 0, "2": 1, "dusra": 1, "doosra": 1, "second": 1, "do": 1,
                "3": 2, "teesra": 2, "tisra": 2, "third": 2, "teen": 2, "4": 3, "chautha": 3, "fourth": 3}
    first = v.split()[0]
    if first in ordinals and ordinals[first] < len(options):
        return options[ordinals[first]]
    for o in options:
        if o.lower() == v:
            return o
    matches = [o for o in options if v in o.lower() or all(w in o.lower() for w in v.split())]
    return matches[0] if len(matches) == 1 else None
