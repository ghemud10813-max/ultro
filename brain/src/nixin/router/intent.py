"""The Intent type shared by the router, the classifier and the executors."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Intent:
    kind: str
    params: dict = field(default_factory=dict)
    source_text: str = ""

    @property
    def external(self) -> bool:
        return self.kind in ("message", "call", "notif_reply")
