"""Plugins: drop a ``.py`` file into ``<data dir>/plugins/`` to add your own commands.

    # ~/.nixin/plugins/dice.py
    import random
    from nixin.features.plugins import command

    @command(r"^(?:dice|pasa) (?:roll|phenko|feko)$", name="dice", description="Roll a dice")
    async def dice(ctx):
        return f"{random.randint(1, 6)} aaya!"

    @command(r"^(?P<what>.+) ki photo pc pe bhejo$")
    async def photo(ctx):
        await ctx.phone("device.global", {"action": "screenshot"})   # any phone method (same safety checks)
        return await ctx.run("PC ka clipboard phone pe bhejo")       # or any Nixin command

The pattern is matched (case-insensitively) against the cleaned command (lowercase, fillers and the
wake word removed). Return a string to reply, or None. Plugins run on YOUR PC with your
permissions — only install plugins you wrote or trust. Messages/calls started through ``ctx.run``
still ask for confirmation (source ``plugin``).
"""

from __future__ import annotations

import importlib.util
import re
import sys
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nixin.features.base import Feature, Intent, Outcome, TaskContext
from nixin.router.normalize import clean

PluginFn = Callable[["PluginContext"], Awaitable[str | None]]


@dataclass
class PluginCommand:
    pattern: re.Pattern
    fn: PluginFn
    name: str
    description: str = ""
    needs_phone: bool = False
    file: str = ""


_REGISTRY: list[PluginCommand] = []


def command(pattern: str, *, name: str | None = None, description: str = "", needs_phone: bool = False):
    """Decorator used by plugin files."""

    def deco(fn: PluginFn) -> PluginFn:
        _REGISTRY.append(PluginCommand(re.compile(pattern, re.I), fn, name or fn.__name__, description, needs_phone))
        return fn

    return deco


@dataclass
class PluginContext:
    text: str
    match: re.Match
    lang: str
    task: TaskContext
    app: Any = field(repr=False, default=None)

    @property
    def groups(self) -> dict[str, str]:
        return {k: v for k, v in self.match.groupdict().items() if v is not None}

    async def phone(self, method: str, params: dict | None = None, timeout: float = 15.0) -> dict:
        return await self.app.phone.call(method, params or {}, task_id=self.task.task_id, origin="plugin", timeout=timeout)

    async def run(self, command_text: str) -> str:
        return await self.app.brain.handle(command_text, source="plugin", queue=True, nested=True, quiet=True,
                                           trusted=False)

    async def say(self, text: str) -> None:
        await self.app.brain.announce(text)

    async def notify(self, title: str, text: str = "") -> None:
        await self.app.brain.notify(title, text)

    def remember(self, fact: str) -> None:
        self.app.memory.remember(fact)

    @property
    def pc(self):
        pcf = getattr(self.app, "pc", None)
        return pcf.pc if pcf else None

    @property
    def http(self):
        return self.app.http


class PluginManager(Feature):
    name = "plugins"
    local = frozenset({"plugin"})

    def __init__(self, app) -> None:
        super().__init__(app)
        self.commands: list[PluginCommand] = []
        self.errors: dict[str, str] = {}
        self.dirs = [app.cfg.data_path / "plugins"] + [Path(d).expanduser() for d in app.cfg.plugins.dirs]
        if app.cfg.plugins.enabled:
            self.load()

    def handlers(self):
        return {"plugin": self.handle}

    def load(self) -> None:
        self.commands, self.errors = [], {}
        for d in self.dirs:
            if not d.is_dir():
                continue
            for f in sorted(d.glob("*.py")):
                if f.name.startswith("_"):
                    continue
                before = len(_REGISTRY)
                try:
                    spec = importlib.util.spec_from_file_location(f"nixin_plugin_{f.stem}", f)
                    assert spec and spec.loader
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[spec.name] = mod
                    spec.loader.exec_module(mod)
                except Exception:  # noqa: BLE001 — a broken plugin must not break Nixin
                    self.errors[str(f)] = traceback.format_exc(limit=3)
                    del _REGISTRY[before:]
                    self.bus.emit("log", level="error", msg=f"Plugin {f.name} failed to load")
                    continue
                for c in _REGISTRY[before:]:
                    c.file = str(f)
                    self.commands.append(c)
                del _REGISTRY[before:]
        if self.commands:
            self.bus.emit("log", level="info", msg=f"Plugins: {', '.join(c.name for c in self.commands)}")

    def describe(self) -> list[dict]:
        return [{"name": c.name, "pattern": c.pattern.pattern, "description": c.description, "file": c.file,
                 "needsPhone": c.needs_phone} for c in self.commands]

    def match(self, text: str) -> tuple[PluginCommand, re.Match] | None:
        c = clean(text)
        for cmd in self.commands:
            m = cmd.pattern.search(c)
            if m:
                return cmd, m
        return None

    async def handle(self, intent: Intent, ctx: TaskContext, *, deterministic: bool = True, origin: str = "router") -> Outcome:
        cmd: PluginCommand = intent.params["command"]
        if cmd.needs_phone and (o := self.offline(ctx)) is not None:
            return o
        pctx = PluginContext(ctx.text, intent.params["match"], ctx.lang, ctx, self.app)
        try:
            out = await cmd.fn(pctx)
        except Exception as e:  # noqa: BLE001
            self.bus.emit("log", level="error", msg=f"Plugin {cmd.name} failed: {e!r}")
            return Outcome(False, f"Plugin '{cmd.name}' error: {e}")
        return Outcome(True, str(out) if out else "")
