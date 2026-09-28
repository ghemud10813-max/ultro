"""Small shared base for feature modules.

A feature registers handlers for intent kinds into ``Actions.handlers``. A handler has
the same signature everywhere: ``async (intent, ctx, *, deterministic, origin) -> Outcome``.
Kinds listed in ``local`` work without a connected phone (PC control, weather, routines…).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from nixin.core.context import Outcome, TaskContext
from nixin.router.router import Intent

if TYPE_CHECKING:
    from nixin.app import NixinApp

Handler = Callable[..., Awaitable[Outcome]]


def tr(ctx: TaskContext | str, hinglish: str, english: str) -> str:
    lang = ctx if isinstance(ctx, str) else ctx.lang
    return english if lang == "english" else hinglish


class Feature:
    name = "feature"
    local: frozenset[str] = frozenset()

    def __init__(self, app: NixinApp) -> None:
        self.app = app
        self.cfg = app.cfg
        self.bus = app.bus
        self.store = app.store
        self.phone = app.phone

    def handlers(self) -> dict[str, Handler]:
        return {}

    def install(self) -> None:
        for kind, fn in self.handlers().items():
            self.app.actions.handlers[kind] = fn
        self.app.brain.local_kinds |= set(self.local)

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    # convenience for handlers
    async def call(self, ctx: TaskContext, method: str, params: dict | None = None, *, origin: str = "router",
                   confirmed: bool = False, timeout: float = 15.0) -> dict:
        return await self.phone.call(method, params or {}, task_id=ctx.task_id, origin=origin, confirmed=confirmed,
                                     timeout=timeout)

    def offline(self, ctx: TaskContext) -> Outcome | None:
        if self.phone.connected:
            return None
        from nixin.core.replies import say

        return Outcome(False, say("offline", ctx.lang), code="device.offline")


__all__ = ["Feature", "Handler", "Intent", "Outcome", "TaskContext", "tr"]
