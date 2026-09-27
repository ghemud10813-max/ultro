"""Per-command context passed through router, actions and agent."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field

# Where a command came from. Voice sources can mis-hear, so they never auto-approve
# external actions (messages, calls) under the "smart" confirmation policy.
SOURCES = ("typed", "dashboard", "phone_text", "phone_voice", "voice", "wake_word", "api")
TRUSTED_TEXT_SOURCES = {"typed", "dashboard", "phone_text", "api"}


@dataclass
class TaskContext:
    source: str = "typed"
    text: str = ""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started: float = field(default_factory=time.time)
    deadline: float = 0.0
    lang: str = "hinglish"
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    notes: list[str] = field(default_factory=list)

    @property
    def is_cancelled(self) -> bool:
        return self.cancelled.is_set()

    @property
    def remaining(self) -> float:
        return max(0.0, self.deadline - time.time()) if self.deadline else 9e9

    @property
    def via_phone(self) -> bool:
        return self.source.startswith("phone_")

    @property
    def spoken(self) -> bool:
        return self.source in ("voice", "wake_word", "phone_voice")


@dataclass
class Outcome:
    ok: bool
    say: str = ""
    data: dict | None = None
    followup_goal: str | None = None  # hand the rest to the phone agent
    followup_hint: str | None = None
    uncertain: bool = False
    code: str | None = None
