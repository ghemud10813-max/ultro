"""The Brain: one entry point for every command (console, voice, dashboard, phone).

    text ──> router (no LLM) ──resolved──> Actions ──> reply
               │ unresolved
               v
           classifier (fast LLM) ──> Actions / phone agent (LangGraph) ──> reply
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Protocol

from nixin.agent.classifier import Classifier
from nixin.agent.graph import PhoneAgent
from nixin.config import NixinConfig
from nixin.core.actions import Actions
from nixin.core.confirm import ConfirmationGate
from nixin.core.context import Outcome, TaskContext
from nixin.core.events import EventBus
from nixin.core.memory import Memory
from nixin.core.replies import say
from nixin.core.store import Store
from nixin.link.phone import PhoneLink
from nixin.link.protocol import PhoneError
from nixin.llm.client import LlmError
from nixin.llm.gateway import Gateway, NoCandidate
from nixin.router.router import Intent, route

_HINDI_WORDS = re.compile(
    r"\b(?:hai|hain|karo|kar|kardo|ko|do|de|bhej|bhejo|bol|bolo|ki|ka|ke|mein|me|pe|par|nahi|kya|aur|kholo|khol|"
    r"chalao|chala|laga|lagao|badha|kam|band|batao|bata|mera|meri|mere|abhi|kal|aaj|baje|yaar|zara|jaldi|ruk|ruko|ja|jao|bas|haan|chal|raha|rahi|hoon|hu|tum|aap|mujhe|kuch|kaise|kyun|kaun|wala|wali|"
    r"sikho|seekho|sikh|dikhao|sunao|yaad|dilana|jab|har|roz|raat|subah|shaam|mausam|barish|baarish|uthao|utha|kaat|kitna|kitni|"
    r"kahan|dhundo|chalaya|bhi|usko|wahi|hogi|hoga|karna|dena|lo|sikha)\b", re.I)


class Speaker(Protocol):
    async def say(self, text: str) -> None: ...
    def stop(self) -> None: ...


# intent kinds that never need the phone (features add theirs at install time)
LOCAL_KINDS = {"chat", "reply", "clarify", "clock", "remember", "alias"}
HUMAN_SOURCES = {"typed", "dashboard", "phone_text", "phone_voice", "voice", "wake_word", "api"}


class Brain:
    def __init__(self, cfg: NixinConfig, store: Store, bus: EventBus, phone: PhoneLink, gateway: Gateway,
                 memory: Memory, gate: ConfirmationGate, actions: Actions) -> None:
        self.cfg = cfg
        self.store = store
        self.bus = bus
        self.phone = phone
        self.gw = gateway
        self.memory = memory
        self.gate = gate
        self.actions = actions
        self.classifier = Classifier(gateway, memory, phone, cfg.assistant.history_turns)
        self.agent = PhoneAgent(cfg, phone, gateway, actions, gate, memory, store, bus)
        self.speaker: Speaker | None = None
        self.current: TaskContext | None = None
        self.app: Any = None  # set by NixinApp; gives access to feature modules (routines, skills, plugins…)
        self.local_kinds: set[str] = set(LOCAL_KINDS)
        self.last_reply: str = ""
        self._lock = asyncio.Lock()
        phone.on_command = self._from_phone
        phone.on_answer = lambda ask_id, value: self.gate.answer(ask_id, value)
        phone.on_stopped = self.cancel_current
        gate.phone_ask = self._phone_ask

    # ------------------------------------------------------------------ entry points
    async def _from_phone(self, text: str, source: str, _msg_id: str | None) -> None:
        await self.handle(text, source)

    async def _phone_ask(self, msg: dict) -> bool:
        return await self.phone.send_message(msg)

    def lang_for(self, text: str) -> str:
        pref = self.cfg.assistant.reply_language
        if pref != "auto":
            return pref
        return "hinglish" if _HINDI_WORDS.search(text) or re.search(r"[ऀ-ॿ]", text) else "english"

    def _feature(self, name: str):
        return getattr(self.app, name, None) if self.app is not None else None

    async def handle(self, text: str, source: str = "typed", *, queue: bool = False, nested: bool = False,
                     quiet: bool = False, trusted: bool = False, event: dict | None = None) -> str:
        """Run one command. ``queue``: wait for a running task instead of answering "busy" (routines).
        ``nested``: the caller already holds the brain (plugins calling ``ctx.run``)."""
        text = (text or "").strip()
        if not text:
            return ""
        human = source in HUMAN_SOURCES
        # A pending question (confirm / choose / clarify) is answered by the next utterance.
        if human and self.gate.pending and self.gate.answer(None, text):
            self.bus.emit("user", text=text, source=source, answer=True)
            return ""
        if human:
            expanded = self.memory.expand_references(text)
            if expanded != text:
                self.bus.emit("log", level="info", msg=f"Understood as: {expanded}")
                text = expanded
        ctx = TaskContext(source=source, text=text, lang=self.lang_for(text),
                          deadline=time.time() + self.cfg.assistant.max_task_seconds,
                          trusted=trusted, event=event or {}, quiet=quiet)
        r = route(text)
        if r.intents and len(r.intents) == 1 and r.intents[0].kind == "cancel":
            self.bus.emit("user", text=text, source=source)
            return await self._respond(ctx, self.cancel_current(ctx.lang))

        # scenes you say out loud ("good night", "study mode") run their routine
        routines = self._feature("routines")
        if human and routines is not None and (scene := routines.match_phrase(text)) is not None:
            return await self._scene(ctx, scene)

        intents = r.intents
        plugins = self._feature("plugins")
        skills = self._feature("skills")
        if source != "plugin" and plugins is not None and (pm := plugins.match(text)) is not None:
            intents = [Intent("plugin", {"command": pm[0], "match": pm[1]}, text)]
        elif skills is not None and (sm := skills.match(text)) is not None:
            intents = [Intent("skill_run", {"id": sm[0].id, "name": sm[0].name, "arg": sm[1]}, text)]

        if nested:
            return await self._run(ctx, intents)
        if self._lock.locked() and not queue:
            self.bus.emit("user", text=text, source=source, rejected="busy")
            return await self._respond(ctx, say("busy", ctx.lang))
        async with self._lock:
            self.current = ctx
            try:
                return await self._run(ctx, intents)
            finally:
                self.current = None

    async def _scene(self, ctx: TaskContext, routine) -> str:
        self.memory.add_turn("user", ctx.text, ctx.task_id)
        self.bus.emit("user", text=ctx.text, source=ctx.source, taskId=ctx.task_id, routine=routine.name)
        if not ctx.via_phone:
            await self.phone.send_message({"t": "echo", "text": ctx.text, "source": ctx.source, "taskId": ctx.task_id})
        replies = await self._feature("routines").run(routine, {}, "phrase", collect=True)
        return await self._respond(ctx, " ".join(replies).strip() or say("done", ctx.lang))

    def cancel_current(self, lang: str = "hinglish") -> str:
        ctx = self.current
        self.gate.cancel_all()
        if self.speaker:
            self.speaker.stop()
        if ctx is None:
            return say("nothing_running", lang)
        ctx.cancelled.set()
        asyncio.create_task(self.phone.cancel(ctx.task_id, "user"))
        self.bus.emit("task", taskId=ctx.task_id, status="cancelling")
        return say("cancelled", lang)

    # ------------------------------------------------------------------ pipeline
    async def _run(self, ctx: TaskContext, intents: list[Intent] | None) -> str:
        self.store.create_task(ctx.task_id, ctx.source, ctx.text)
        self.memory.add_turn("user", ctx.text, ctx.task_id)
        self.bus.emit("user", text=ctx.text, source=ctx.source, taskId=ctx.task_id)
        self.bus.emit("task", taskId=ctx.task_id, status="running", text=ctx.text, source=ctx.source)
        if not ctx.via_phone and not ctx.quiet:
            # keep the phone app's chat in sync with commands given on the PC
            await self.phone.send_message({"t": "echo", "text": ctx.text, "source": ctx.source, "taskId": ctx.task_id})
        outcomes: list[Outcome] = []
        route_kind = "router"
        try:
            if intents:
                self.store.update_task(ctx.task_id, route="router")
                outcomes = await self._run_intents(ctx, intents, deterministic=True, origin="router")
            elif not self.gw.any_ready() or not self.cfg.privacy.cloud_llm:
                route_kind = "none"
                outcomes = [Outcome(False, say("llm_off" if not self.gw.any_ready() else "not_understood", ctx.lang))]
            else:
                route_kind = "classifier"
                self.store.update_task(ctx.task_id, route="classifier")
                try:
                    cls = await self.classifier.classify(ctx.text, deadline=ctx.deadline)
                except NoCandidate as e:
                    outcomes = [Outcome(False, say("llm_busy", ctx.lang) if "busy" in str(e) else str(e))]
                except LlmError as e:
                    outcomes = [Outcome(False, say("failed", ctx.lang, reason=str(e)))]
                else:
                    self.store.add_step(ctx.task_id, "classify", {"model": cls.model,
                                                                  "intents": [i.kind for i in cls.intents]})
                    self.bus.emit("classified", taskId=ctx.task_id, model=cls.model,
                                  intents=[{"kind": i.kind, "params": i.params} for i in cls.intents])
                    if any(i.kind == "agent" for i in cls.intents):
                        route_kind = "agent"
                    outcomes = await self._run_intents(ctx, cls.intents, deterministic=False, origin="classifier")
        except asyncio.CancelledError:
            outcomes.append(Outcome(False, say("cancelled", ctx.lang)))
        except Exception as e:  # noqa: BLE001
            self.bus.emit("log", level="error", msg=f"Task failed: {e!r}")
            outcomes.append(Outcome(False, say("failed", ctx.lang, reason=str(e)[:120])))

        if ctx.is_cancelled and not any(o.say == say("cancelled", ctx.lang) for o in outcomes):
            outcomes.append(Outcome(False, say("cancelled", ctx.lang)))
        text = " ".join(o.say for o in outcomes if o.say).strip() or say("done", ctx.lang)
        ok = all(o.ok for o in outcomes) if outcomes else False
        status = "cancelled" if ctx.is_cancelled else ("uncertain" if any(o.uncertain for o in outcomes)
                                                       else ("done" if ok else "failed"))
        self.store.finish_task(ctx.task_id, status, text)
        self.store.update_task(ctx.task_id, route=route_kind)
        self.bus.emit("task", taskId=ctx.task_id, status=status, route=route_kind, summary=text)
        return await self._respond(ctx, text)

    async def _run_intents(self, ctx: TaskContext, intents: list[Intent], *, deterministic: bool,
                           origin: str) -> list[Outcome]:
        outcomes: list[Outcome] = []
        for intent in intents:
            if ctx.is_cancelled:
                break
            self.bus.emit("intent", taskId=ctx.task_id, kind=intent.kind, params=intent.params, origin=origin)
            if intent.kind == "agent":
                o = await self._agent(ctx, intent.params["goal"], intent.params.get("hint"))
            else:
                needs_phone = intent.kind not in self.local_kinds
                if needs_phone and not self.phone.connected:
                    outcomes.append(Outcome(False, say("offline", ctx.lang), code="device.offline"))
                    break
                o = await self.actions.run_intent(intent, ctx, deterministic=deterministic, origin=origin)
                if o.followup_goal and not ctx.is_cancelled:
                    if self.gw.role_ready("planner") and self.cfg.privacy.cloud_llm:
                        follow = await self._agent(ctx, o.followup_goal, o.followup_hint, announce=False, max_steps=6)
                        o = Outcome(follow.ok, follow.say or o.say, uncertain=follow.uncertain) if follow.say else o
            outcomes.append(o)
            if not o.ok:
                break
        return outcomes

    async def _agent(self, ctx: TaskContext, goal: str, hint: str | None = None, *, announce: bool = True,
                     max_steps: int | None = None) -> Outcome:
        if not self.phone.connected:
            return Outcome(False, say("offline", ctx.lang), code="device.offline")
        if not self.gw.role_ready("planner"):
            return Outcome(False, say("llm_off", ctx.lang))
        if announce and ctx.spoken:
            await self._speak_only(ctx, say("working", ctx.lang))
        self.store.update_task(ctx.task_id, route="agent")
        skills = self._feature("skills")
        if skills is not None and skills.auto_replay and (known := skills.auto_for(goal)) is not None:
            ok, idx, err = await skills.replay(known, ctx)
            known.runs += 1
            if ok:
                known.fails = 0
                skills.save(known)
                self.store.update_task(ctx.task_id, route="skill")
                return Outcome(True, say("done", ctx.lang), {"skill": known.id})
            known.fails += 1
            skills.save(known)
            if ctx.is_cancelled:
                return Outcome(False, say("cancelled", ctx.lang))
            hint = ((hint or "") + f" (A saved route stopped at step {idx + 1}: {err}. Continue from the current screen.)").strip()
        res = await self.agent.run(goal, ctx, hint=hint, max_steps=max_steps)
        if res.status == "done" and skills is not None and not res.answer:
            try:
                skills.learn_from_agent(goal, res.history)
            except Exception as e:  # noqa: BLE001
                self.bus.emit("log", level="warning", msg=f"Could not save the learned route: {e!r}")
        if res.status == "done":
            return Outcome(True, res.answer or res.summary or say("done", ctx.lang), {"steps": res.steps})
        if res.status == "cancelled":
            return Outcome(False, say("cancelled", ctx.lang))
        if res.status == "uncertain":
            return Outcome(False, res.summary, uncertain=True)
        return Outcome(False, say("failed", ctx.lang, reason=res.summary))

    # ------------------------------------------------------------------ replies
    def _targets(self, ctx: TaskContext) -> tuple[bool, bool]:
        """-> (speak on PC, speak on phone)"""
        mode = self.cfg.assistant.reply_on
        if mode == "pc":
            return True, False
        if mode == "phone":
            return False, True
        if mode == "both":
            return True, True
        if ctx.via_phone:
            return False, ctx.source == "phone_voice"
        return ctx.source in ("voice", "wake_word"), False

    async def _speak_only(self, ctx: TaskContext, text: str) -> None:
        pc, ph = self._targets(ctx)
        if pc and self.speaker:
            asyncio.create_task(self.speaker.say(text))
        if ph:
            await self.phone.say(text, speak=True, task_id=ctx.task_id)

    async def _respond(self, ctx: TaskContext, text: str) -> str:
        if ctx.quiet:
            self.bus.emit("say", text=text, taskId=ctx.task_id, source=ctx.source, quiet=True)
            return text
        self.memory.add_turn("nixin", text, ctx.task_id)
        self.last_reply = text
        self.bus.emit("say", text=text, taskId=ctx.task_id, source=ctx.source)
        pc, ph = self._targets(ctx)
        if pc and self.speaker:
            asyncio.create_task(self.speaker.say(text))
        # always mirror the conversation into the phone app's chat; speak there only if targeted
        await self.phone.say(text, speak=ph, task_id=ctx.task_id)
        return text

    # ------------------------------------------------------------------ proactive output (routines, alerts)
    async def announce(self, text: str) -> None:
        """Speak something Nixin decided to say on its own (routine, VIP message, battery alert)."""
        text = (text or "").strip()
        if not text:
            return
        self.bus.emit("say", text=text, source="announce")
        mode = self.cfg.assistant.announce_on
        if mode in ("pc", "both") and self.speaker:
            asyncio.create_task(self.speaker.say(text))
        await self.phone.say(text, speak=mode in ("phone", "both"))

    async def post(self, text: str) -> None:
        """Show a line in the chats (dashboard + phone) without speaking it."""
        self.bus.emit("say", text=text, source="announce", silent=True)
        await self.phone.say(text, speak=False)

    async def notify(self, title: str, text: str = "") -> None:
        """A notification on the phone and on the PC desktop."""
        self.bus.emit("notify", title=title, text=text)
        if self.phone.connected:
            try:
                await self.phone.call("nixin.notify", {"title": title[:120] or "Nixin", "text": text[:1000]}, origin="routine")
            except PhoneError:
                pass
        pcf = self._feature("pc")
        if pcf is not None:
            await pcf.pc.notify(title, text)
