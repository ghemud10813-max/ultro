"""The phone agent: a bounded LangGraph loop  observe -> plan -> act -> (verify) -> ...

                 ┌──────────────────────────────────────────┐
                 v                                          │
  START ──> observe ──> plan ──> act ──┬── ui/tool action ──┘
                          ^           ├── done ──> verify ──┬──> END (verified)
                          │           │                     └──> observe (not done yet)
                          └── invalid ┘── fail / limits / cancel ──> END

* One tool call per LLM turn; every call is validated against the latest snapshot.
* Each turn is a fresh, compact prompt (goal + short progress log + current screen)
  instead of an ever-growing chat, which keeps each call ~1.5–3k tokens.
* Hard limits: max steps, deadline, repeated-action and no-progress detection.
"""

from __future__ import annotations

import asyncio
import base64
import io
import time
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from nixin.agent import prompts
from nixin.agent.screen import find_element, render, screen_hash
from nixin.agent.tools import (
    PLANNER_TOOLS,
    TERMINAL_TOOLS,
    UI_TOOLS,
    action_signature,
    check_tool,
    describe_call,
)
from nixin.config import NixinConfig
from nixin.core.actions import Actions
from nixin.core.confirm import ConfirmationGate
from nixin.core.context import TaskContext
from nixin.core.events import EventBus
from nixin.core.memory import Memory
from nixin.core.store import Store
from nixin.link.phone import PhoneLink
from nixin.link.protocol import PhoneError
from nixin.llm.client import ChatResult, extract_json
from nixin.llm.gateway import Gateway, NoCandidate


class AgentState(TypedDict, total=False):
    goal: str
    hint: str
    step: int
    max_steps: int
    deadline: float
    history: list[dict]
    screen: dict | None
    screen_text: str
    screen_hash: str
    stale_count: int
    last_sig: str
    repeat_count: int
    pending: dict | None
    note: str
    llm_errors: int
    verify_rounds: int
    outcome: dict | None


@dataclass
class AgentResult:
    status: str  # done | failed | cancelled | uncertain
    summary: str
    answer: str | None = None
    steps: int = 0
    history: list[dict] = field(default_factory=list)


FATAL_PHONE_CODES = {"device.offline", "policy.stopped", "device.locked", "policy.blocked_app",
                     "permission.accessibility", "action.uncertain", "cancelled"}


class PhoneAgent:
    def __init__(self, cfg: NixinConfig, phone: PhoneLink, gateway: Gateway, actions: Actions,
                 gate: ConfirmationGate, memory: Memory, store: Store, bus: EventBus) -> None:
        self.cfg = cfg
        self.phone = phone
        self.gw = gateway
        self.actions = actions
        self.gate = gate
        self.memory = memory
        self.store = store
        self.bus = bus
        self.graph: CompiledStateGraph = self._build()

    # ------------------------------------------------------------------ graph
    def _build(self) -> CompiledStateGraph:
        g = StateGraph(AgentState)
        g.add_node("observe", self._observe)
        g.add_node("plan", self._plan)
        g.add_node("act", self._act)
        g.add_node("verify", self._verify)
        g.add_edge(START, "observe")
        g.add_conditional_edges("observe", self._after_observe, {"plan": "plan", "end": END})
        g.add_conditional_edges("plan", self._after_plan, {"act": "act", "plan": "plan", "end": END})
        g.add_conditional_edges("act", self._after_act, {"observe": "observe", "verify": "verify", "end": END})
        g.add_conditional_edges("verify", self._after_verify, {"observe": "observe", "end": END})
        return g.compile()

    async def run(self, goal: str, ctx: TaskContext, hint: str | None = None, max_steps: int | None = None) -> AgentResult:
        max_steps = max_steps or self.cfg.assistant.max_agent_steps
        deadline = min(ctx.deadline or 9e18, time.time() + self.cfg.assistant.max_task_seconds)
        state: AgentState = {
            "goal": goal, "hint": hint or "", "step": 0, "max_steps": max_steps, "deadline": deadline,
            "history": [], "screen": None, "screen_text": "", "screen_hash": "", "stale_count": 0,
            "last_sig": "", "repeat_count": 0, "pending": None, "note": "", "llm_errors": 0,
            "verify_rounds": 0, "outcome": None,
        }
        self._emit(ctx, "start", goal=goal, maxSteps=max_steps)
        try:
            final = await self.graph.ainvoke(state, config={"recursion_limit": max_steps * 4 + 20,
                                                            "configurable": {"ctx": ctx}})
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — never crash the brain because of the agent
            self._emit(ctx, "error", error=repr(e))
            return AgentResult("failed", f"Agent error: {e}", steps=state.get("step", 0))
        out = final.get("outcome") or {"status": "failed", "summary": "Stopped without a result."}
        res = AgentResult(out["status"], out.get("summary", ""), out.get("answer"), final.get("step", 0),
                          final.get("history", []))
        self._emit(ctx, "end", status=res.status, summary=res.summary, answer=res.answer, steps=res.steps)
        return res

    # ------------------------------------------------------------------ nodes
    async def _observe(self, state: AgentState, config: dict) -> dict:
        ctx: TaskContext = config["configurable"]["ctx"]
        if (o := self._check_stop(state, ctx)) is not None:
            return {"outcome": o}
        try:
            snap = await self.phone.call("ui.snapshot", {"maxElements": 150}, task_id=ctx.task_id, origin="agent", timeout=10)
        except PhoneError as e:
            if e.code in FATAL_PHONE_CODES or e.code.startswith("permission."):
                return {"outcome": {"status": "failed", "summary": self.actions.error_outcome(e, ctx).say}}
            await asyncio.sleep(0.8)
            return {"note": f"Could not read the screen ({e.code}); retrying.", "screen": None, "screen_text": "(unreadable)"}
        h = screen_hash(snap)
        last = state.get("history") or []
        stale = state.get("stale_count", 0)
        if last and last[-1].get("tool") in UI_TOOLS and h == state.get("screen_hash"):
            stale += 1
        elif h != state.get("screen_hash"):
            stale = 0
        text = render(snap)
        self._emit(ctx, "observe", package=snap.get("package"), app=snap.get("app"), elements=len(snap.get("elements") or []),
                   screen=text)
        return {"screen": snap, "screen_text": text, "screen_hash": h, "stale_count": stale}

    def _after_observe(self, state: AgentState) -> str:
        return "end" if state.get("outcome") else "plan"

    async def _plan(self, state: AgentState, config: dict) -> dict:
        ctx: TaskContext = config["configurable"]["ctx"]
        if (o := self._check_stop(state, ctx)) is not None:
            return {"outcome": o}
        note = state.get("note") or ""
        if state.get("stale_count", 0) >= 2:
            note = (note + " The screen did not change after your last actions — try something different "
                    "(another element, scroll, back) or fail.").strip()
        hint = f"\nHINT: {state['hint']}" if state.get("hint") else ""
        mem = self.memory.prompt_block(state["goal"], history_turns=0)
        user = prompts.PLANNER_USER.format(
            goal=state["goal"], hint=hint, memory=(mem + "\n") if mem else "",
            progress=self._progress(state) or "(nothing yet)",
            note=f"\nNOTE: {note}" if note else "", step=state.get("step", 0) + 1, max_steps=state["max_steps"],
            screen=state.get("screen_text") or "(unknown)",
        )
        messages = [{"role": "system", "content": prompts.PLANNER_SYSTEM}, {"role": "user", "content": user}]
        try:
            res: ChatResult = await self.gw.complete("planner", messages, tools=PLANNER_TOOLS, tool_choice="required",
                                                     deadline=state["deadline"])
        except NoCandidate as e:
            return {"outcome": {"status": "failed", "summary": str(e)}}
        call = self._pick_call(res, state)
        if call is None:
            errs = state.get("llm_errors", 0) + 1
            if errs >= 3:
                return {"llm_errors": errs, "outcome": {"status": "failed", "summary": "The model did not choose an action."}}
            return {"llm_errors": errs, "pending": None, "note": "You must call exactly one tool."}
        name, args = call
        vision_ready = self.cfg.privacy.cloud_vision and self.gw.role_ready("vision")
        chk = check_tool(name, args, state.get("screen"), vision_ready)
        self._emit(ctx, "plan", tool=name, args=_safe_args(name, args), model=res.candidate, valid=chk.ok,
                   error=chk.error or None, thought=(res.content or "")[:200] or None)
        if not chk.ok:
            errs = state.get("llm_errors", 0) + 1
            if errs >= 4:
                return {"llm_errors": errs, "outcome": {"status": "failed", "summary": f"Invalid actions: {chk.error}"}}
            return {"llm_errors": errs, "pending": None, "note": chk.error}
        return {"pending": {"tool": name, "args": args}, "llm_errors": 0, "note": ""}

    def _after_plan(self, state: AgentState) -> str:
        if state.get("outcome"):
            return "end"
        return "act" if state.get("pending") else "plan"

    async def _act(self, state: AgentState, config: dict) -> dict:
        ctx: TaskContext = config["configurable"]["ctx"]
        if (o := self._check_stop(state, ctx)) is not None:
            return {"outcome": o}
        pend = state["pending"] or {}
        name, args = pend["tool"], dict(pend["args"])
        step = state.get("step", 0) + 1
        history = list(state.get("history") or [])

        if name == "done":
            history.append({"n": step, "tool": name, "args": _safe_args(name, args), "ok": True, "result": "claimed done"})
            return {"history": history, "step": step, "pending": None,
                    "outcome": {"status": "done", "summary": str(args.get("summary") or "Done"),
                                "answer": args.get("answer")}}
        if name == "fail":
            history.append({"n": step, "tool": name, "args": args, "ok": False, "result": "gave up"})
            return {"history": history, "step": step, "pending": None,
                    "outcome": {"status": "failed", "summary": str(args.get("reason") or "Could not complete the task")}}

        sig = action_signature(name, args) + "@" + (state.get("screen_hash") or "")
        repeat = state.get("repeat_count", 0) + 1 if sig == state.get("last_sig") else 0
        if repeat >= 2:
            return {"history": history, "step": step, "pending": None,
                    "outcome": {"status": "failed", "summary": "Got stuck repeating the same action."}}

        ok, result, fatal = await self._execute(name, args, state, ctx)
        history.append({"n": step, "tool": name, "args": _safe_args(name, args), "ok": ok, "result": result})
        self._emit(ctx, "act", n=step, tool=name, args=_safe_args(name, args), ok=ok, result=result)
        self.store.add_step(ctx.task_id, "act", {"n": step, "tool": name, "ok": ok, "result": result})
        out: dict[str, Any] = {"history": history, "step": step, "pending": None, "last_sig": sig, "repeat_count": repeat,
                               "note": "" if ok else f"Last action failed: {result}"}
        if fatal:
            out["outcome"] = fatal
        elif step >= state["max_steps"]:
            out["outcome"] = {"status": "failed", "summary": f"Step limit ({state['max_steps']}) reached."}
        elif time.time() > state["deadline"]:
            out["outcome"] = {"status": "failed", "summary": "Time limit reached."}
        return out

    def _after_act(self, state: AgentState) -> str:
        o = state.get("outcome")
        if not o:
            return "observe"
        if o["status"] == "done" and self.cfg.assistant.verify_finish and state.get("verify_rounds", 0) < 2 \
                and self.gw.role_ready("verifier") and (state.get("history") or [])[:-1]:
            return "verify"
        return "end"

    async def _verify(self, state: AgentState, config: dict) -> dict:
        ctx: TaskContext = config["configurable"]["ctx"]
        claim = state["outcome"] or {}
        try:
            await asyncio.sleep(0.6)
            snap = await self.phone.call("ui.snapshot", {"maxElements": 120}, task_id=ctx.task_id, origin="agent", timeout=10)
            screen = render(snap, max_chars=3000)
        except PhoneError:
            return {"verify_rounds": state.get("verify_rounds", 0) + 1}  # keep the claim
        msgs = [
            {"role": "system", "content": prompts.VERIFIER_SYSTEM},
            {"role": "user", "content": prompts.VERIFIER_USER.format(
                goal=state["goal"], progress=self._progress(state), claim=claim.get("summary", ""), screen=screen)},
        ]
        try:
            res = await self.gw.complete("verifier", msgs, deadline=state["deadline"], max_wait=6)
        except NoCandidate:
            return {"verify_rounds": state.get("verify_rounds", 0) + 1}
        verdict = extract_json(res.content) or {}
        done = verdict.get("done")
        self._emit(ctx, "verify", done=done, reason=verdict.get("reason"), model=res.candidate)
        rounds = state.get("verify_rounds", 0) + 1
        if done is False and state.get("step", 0) < state["max_steps"] and time.time() < state["deadline"]:
            return {"verify_rounds": rounds, "outcome": None,
                    "note": f"A checker says the goal is NOT complete yet: {verdict.get('reason', '')}. Continue."}
        return {"verify_rounds": rounds}

    def _after_verify(self, state: AgentState) -> str:
        return "end" if state.get("outcome") else "observe"

    # ------------------------------------------------------------------ execution
    async def _execute(self, name: str, args: dict, state: AgentState, ctx: TaskContext) -> tuple[bool, str, dict | None]:
        snap = state.get("screen") or {}
        sid = snap.get("snapshotId")
        call = self.phone.call
        kw = {"task_id": ctx.task_id, "origin": "agent"}
        try:
            if name == "tap" or name == "long_press":
                method = "ui.tap" if name == "tap" else "ui.long_press"
                el = find_element(snap, int(args["id"]))
                try:
                    await call(method, {"snapshotId": sid, "elementId": int(args["id"])}, **kw)
                except PhoneError as e:
                    if e.code != "policy.confirmation_required":
                        raise
                    label = (el or {}).get("text") or (el or {}).get("desc") or f"[{args['id']}]"
                    ans = await self.gate.ask(
                        f"'{label}' dabana hai ({snap.get('app')}) — isse kuch bheja/badla ja sakta hai. Karun?"
                        if ctx.lang != "english" else f"Tap '{label}' in {snap.get('app')}? It may send or change something.",
                        kind="confirm", task_id=ctx.task_id, source=ctx.source)
                    if ans != "yes":
                        return False, "user declined this action", {"status": "failed", "summary": "Cancelled by you."}
                    await call(method, {"snapshotId": sid, "elementId": int(args["id"])}, confirmed=True, **kw)
                await asyncio.sleep(0.7)
                return True, f"tapped {(el or {}).get('text') or (el or {}).get('desc') or ''}".strip(), None
            if name == "type_text":
                p: dict = {"text": str(args["text"]), "clear": True, "submit": bool(args.get("submit"))}
                if args.get("id") is not None:
                    p["snapshotId"], p["elementId"] = sid, int(args["id"])
                await call("ui.type", p, **kw)
                await asyncio.sleep(0.5 if not p["submit"] else 1.2)
                return True, "typed" + (" and submitted" if p["submit"] else ""), None
            if name == "scroll":
                p = {"direction": args["direction"]}
                if args.get("id") is not None:
                    p["snapshotId"], p["elementId"] = sid, int(args["id"])
                await call("ui.scroll", p, **kw)
                await asyncio.sleep(0.6)
                return True, "scrolled", None
            if name == "press":
                key = args["key"]
                if key == "enter":
                    await call("ui.key", {"key": "enter"}, **kw)
                else:
                    await call("device.global", {"action": key}, **kw)
                await asyncio.sleep(0.7)
                return True, f"pressed {key}", None
            if name == "swipe":
                await call("ui.swipe", {k: int(args[k]) for k in ("x1", "y1", "x2", "y2")}, **kw)
                await asyncio.sleep(0.6)
                return True, "swiped", None
            if name == "tap_xy":
                await call("ui.tap", {"x": int(args["x"]), "y": int(args["y"])}, **kw)
                await asyncio.sleep(0.7)
                return True, "tapped point", None
            if name == "open_app":
                o = await self.actions.open_app(ctx, str(args["name"]), origin="agent")
                await asyncio.sleep(1.5)
                return o.ok, o.say, None
            if name == "wait":
                await asyncio.sleep(max(0.5, min(5.0, float(args.get("seconds") or 1))))
                return True, "waited", None
            if name == "look":
                answer = await self.look(str(args["question"]), snap, ctx)
                return True, f"vision: {answer}", None
            if name == "send_message":
                o = await self.actions.message(ctx, args.get("channel") or "default", str(args["to"]), str(args["text"]),
                                               deterministic=False, origin="agent")
                if o.uncertain:
                    return False, o.say, {"status": "uncertain", "summary": o.say}
                if o.code == "declined":
                    return False, o.say, {"status": "failed", "summary": o.say}
                return o.ok, o.say, None
            if name == "call_contact":
                o = await self.actions.call_contact(ctx, str(args["to"]), deterministic=False, origin="agent")
                if o.code == "declined":
                    return False, o.say, {"status": "failed", "summary": o.say}
                return o.ok, o.say, None
            if name == "read_notifications":
                o = await self.actions.notifications(ctx, args.get("app"), int(args.get("limit") or 5), origin="agent")
                return o.ok, o.say[:600], None
            if name == "ask_user":
                ans = await self.gate.ask(str(args["question"]), kind="input", task_id=ctx.task_id, source=ctx.source,
                                          timeout=45)
                if not ans:
                    return False, "user did not answer", {"status": "failed", "summary": "No answer from you."}
                return True, f"user answered: {ans[:200]}", None
        except PhoneError as e:
            if e.code in FATAL_PHONE_CODES or e.code.startswith("permission."):
                o = self.actions.error_outcome(e, ctx)
                return False, e.code, {"status": "uncertain" if o.uncertain else "failed", "summary": o.say}
            return False, f"{e.code}: {e.message}", None
        return False, f"unknown tool {name}", None

    async def look(self, question: str, snap: dict, ctx: TaskContext) -> str:
        """Screenshot + set-of-marks overlay -> vision model answer."""
        cap = await self.phone.call("screen.capture", {"maxWidth": 720, "quality": 60}, task_id=ctx.task_id,
                                    origin="agent", timeout=12)
        img_b64 = cap["data"]
        try:
            img_b64 = annotate(img_b64, snap, cap.get("screenWidth") or snap.get("width"))
        except Exception:
            pass
        sw, sh = cap.get("screenWidth") or snap.get("width"), cap.get("screenHeight") or snap.get("height")
        msgs = [
            {"role": "system", "content": prompts.VISION_SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": f"Original screen size: {sw}x{sh}. Boxes labelled with numbers are element ids "
                                         f"the agent can tap. Question: {question}"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
            ]},
        ]
        res = await self.gw.complete("vision", msgs, has_image=True, max_wait=6)
        self._emit(ctx, "look", question=question, answer=res.content[:400], model=res.candidate)
        return res.content[:500]

    # ------------------------------------------------------------------ helpers
    def _pick_call(self, res: ChatResult, state: AgentState) -> tuple[str, dict] | None:
        if res.tool_calls:
            tc = res.tool_calls[0]
            return tc.name, tc.arguments
        j = extract_json(res.content)
        if j and isinstance(j.get("tool") or j.get("name"), str):
            return str(j.get("tool") or j.get("name")), dict(j.get("args") or j.get("arguments") or {})
        if res.content and state.get("step", 0) > 0 and len(res.content) < 400:
            return "done", {"summary": res.content}
        return None

    def _progress(self, state: AgentState) -> str:
        hist = state.get("history") or []
        lines = []
        for h in hist[-8:]:
            mark = "ok" if h.get("ok") else "FAILED"
            lines.append(f"{h['n']}. {describe_call(h['tool'], h.get('args') or {})} -> {mark}: {str(h.get('result'))[:120]}")
        if len(hist) > 8:
            lines.insert(0, f"({len(hist) - 8} earlier steps omitted)")
        return "\n".join(lines)

    def _check_stop(self, state: AgentState, ctx: TaskContext) -> dict | None:
        if ctx.is_cancelled:
            return {"status": "cancelled", "summary": "Cancelled."}
        if self.phone.stopped:
            return {"status": "cancelled", "summary": "Kill switch is on."}
        if time.time() > state["deadline"]:
            return {"status": "failed", "summary": "Time limit reached."}
        return None

    def _emit(self, ctx: TaskContext, kind: str, **data: Any) -> None:
        self.bus.emit("agent", taskId=ctx.task_id, kind=kind, **data)
        if kind in ("start", "plan", "verify", "look", "end", "error"):
            self.store.add_step(ctx.task_id, kind, data)


def _safe_args(name: str, args: dict) -> dict:
    a = dict(args)
    if name == "type_text" and isinstance(a.get("text"), str) and len(a["text"]) > 60:
        a["text"] = a["text"][:57] + "..."
    return a


def annotate(img_b64: str, snap: dict, screen_width: int | None) -> str:
    """Draw element boxes + ids on the screenshot (set-of-marks) so the vision model can reference them."""
    from PIL import Image, ImageDraw

    img = Image.open(io.BytesIO(base64.b64decode(img_b64))).convert("RGB")
    scale = img.width / float(screen_width or img.width)
    d = ImageDraw.Draw(img)
    for e in (snap.get("elements") or [])[:120]:
        b = e.get("b")
        if not b or not ({"click", "edit", "scroll", "long"} & set(e.get("flags") or [])):
            continue
        x1, y1, x2, y2 = (int(v * scale) for v in b)
        d.rectangle([x1, y1, x2, y2], outline=(255, 0, 80), width=2)
        d.rectangle([x1, y1, x1 + 7 * len(str(e["id"])) + 6, y1 + 13], fill=(255, 0, 80))
        d.text((x1 + 3, y1), str(e["id"]), fill=(255, 255, 255))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=70)
    return base64.b64encode(out.getvalue()).decode()
