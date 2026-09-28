"""Skills: tasks Nixin learned by watching you (teach mode) or from its own successful agent runs.

Teach mode
  "Nixin, sikho: chai order"  → the phone records your taps/typing as *semantic* steps
                                 (the tapped element's text / description / view id, never raw pixels only)
  "save karo"                  → steps are stored as a skill
  "chai order chalao"          → replayed step by step with checks, no LLM needed
  "swiggy search: biryani"     → the first typed text is replaced by the argument

Auto skills
  When the phone agent finishes a UI task successfully, the route it took is saved. Next time the
  same goal comes in it is replayed directly (fast, zero tokens); if the replay breaks anywhere the
  agent takes over from the current screen.
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import asdict, dataclass, field

from nixin.features.base import Feature, Intent, Outcome, TaskContext, tr
from nixin.link.protocol import PhoneError
from nixin.router.normalize import clean

REPLAYABLE = {"open", "tap", "type", "scroll", "back", "home", "key", "wait", "find"}
_STEP_PAUSE = 0.6


@dataclass
class Skill:
    name: str
    steps: list[dict]
    kind: str = "taught"  # taught | auto
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    goal: str | None = None  # auto skills: the goal they achieve
    created_at: float = field(default_factory=time.time)
    runs: int = 0
    fails: int = 0
    last_run: float | None = None
    package: str | None = None

    @property
    def param_step(self) -> int | None:
        for i, s in enumerate(self.steps):
            if s.get("a") == "type":
                return i
        return None


def describe_step(s: dict) -> str:
    a = s.get("a")
    if a == "open":
        return f"open {s.get('label') or s.get('package')}"
    if a == "tap":
        return f"tap '{s.get('text') or s.get('desc') or s.get('res') or '?'}'"
    if a == "type":
        return f"type '{s.get('text', '')}'"
    if a == "scroll":
        return f"scroll {s.get('dir', 'down')}"
    if a == "find":
        return f"scroll to '{s.get('text', '')}'"
    if a == "key":
        return f"press {s.get('key', 'enter')}"
    return str(a)


def steps_from_agent(history: list[dict]) -> list[dict] | None:
    """Convert a successful agent history into replayable steps (None if any step can't be replayed)."""
    steps: list[dict] = []
    for h in history:
        tool, args, ok = h.get("tool"), h.get("args") or {}, h.get("ok")
        if tool in ("done",):
            break
        if not ok:
            continue  # failed attempts are not part of the route
        if tool == "open_app":
            steps.append({"a": "open", "label": str(args.get("name") or "")})
        elif tool == "tap":
            el = h.get("el") or {}
            if el.get("text") or el.get("desc") or el.get("res"):
                steps.append({"a": "tap", **el})
                continue
            m = re.match(r"tapped (.+)$", str(h.get("result") or ""))
            if not m or not m.group(1).strip():
                return None
            steps.append({"a": "tap", "text": m.group(1).strip()})
        elif tool == "type_text":
            text = str(args.get("text") or "")
            if len(text) == 60 and text.endswith("..."):
                return None  # the history only kept a shortened copy
            steps.append({"a": "type", "text": text, "submit": bool(args.get("submit"))})
        elif tool == "find_text":
            steps.append({"a": "find", "text": str(args.get("text") or ""), "dir": args.get("direction") or "down"})
        elif tool == "scroll":
            steps.append({"a": "scroll", "dir": args.get("direction") or "down"})
        elif tool == "press":
            k = args.get("key")
            steps.append({"a": "key", "key": "enter"} if k == "enter" else {"a": k})
        elif tool == "wait":
            steps.append({"a": "wait", "seconds": float(args.get("seconds") or 1)})
        else:
            return None  # look / messages / calls / questions are not replayed blindly
    if not steps or steps[0]["a"] != "open":
        return None  # only routes that start from a known place are safe to replay
    return steps if len([s for s in steps if s["a"] != "wait"]) >= 2 else None


class Skills(Feature):
    name = "skills"
    local = frozenset({"skill_list", "skill_delete"})

    def __init__(self, app) -> None:
        super().__init__(app)
        self.skills: dict[str, Skill] = {}
        self.recording: dict | None = None
        self.pause, self.open_pause = _STEP_PAUSE, 1.4  # seconds between replayed steps / after opening an app
        self.auto_replay = bool(self.store.get_setting("skills_auto_replay", True))
        self.load()

    def handlers(self):
        return {"skill_teach": self.teach, "skill_save": self.save_recording, "skill_cancel": self.cancel_recording,
                "skill_run": self.run_intent, "skill_list": self.list_intent, "skill_delete": self.delete_intent}

    # ------------------------------------------------------------------ storage
    def load(self) -> None:
        self.skills = {}
        for d in self.store.list_skills():
            try:
                s = Skill(**d)
                self.skills[s.id] = s
            except TypeError:
                continue

    def save(self, s: Skill) -> Skill:
        self.skills[s.id] = s
        self.store.save_skill(s.id, s.name, s.kind, asdict(s))
        self.bus.emit("skills_changed")
        return s

    def delete(self, sid: str) -> bool:
        s = self.skills.pop(sid, None)
        self.store.delete_skill(sid)
        self.bus.emit("skills_changed")
        return s is not None

    def list(self) -> list[Skill]:
        return sorted(self.skills.values(), key=lambda s: (s.kind != "taught", s.name.lower()))

    def find(self, name: str) -> Skill | None:
        n = clean(name)
        taught = [s for s in self.skills.values() if s.kind == "taught"]
        for s in taught:
            if clean(s.name) == n:
                return s
        cands = [s for s in taught if n and (n in clean(s.name) or clean(s.name) in n)]
        return cands[0] if len(cands) == 1 else None

    def match(self, text: str) -> tuple[Skill, str | None] | None:
        """"chai order chalao" / "run chai order" / "chai order: masala" -> (skill, argument)."""
        t = text.strip()
        for s in sorted((s for s in self.skills.values() if s.kind == "taught"), key=lambda s: -len(s.name)):
            name = r"\s+".join(re.escape(w) for w in s.name.split())
            m = re.match(rf"^(?:nixin[\s,]+)?(?:run\s+|chalao\s+)?(?:skill\s+)?{name}(?:\s+(?:skill|routine))?"
                         rf"(?:\s+(?:chalao|chala do|chala|karo|kar do|run karo|run|shuru karo))?"
                         rf"(?:\s*[:,\-]\s*(?P<arg>.+?))?\s*[.!]?$", t, flags=re.I)
            if m:
                return s, (m.group("arg") or None)
        return None

    def auto_for(self, goal: str) -> Skill | None:
        g = clean(goal)
        for s in self.skills.values():
            if s.kind == "auto" and s.goal and clean(s.goal) == g and s.fails < 3:
                return s
        return None

    def learn_from_agent(self, goal: str, history: list[dict]) -> Skill | None:
        steps = steps_from_agent(history)
        if not steps:
            return None
        existing = self.auto_for(goal)
        if existing:
            existing.steps, existing.fails = steps, 0
            return self.save(existing)
        return self.save(Skill(name=goal[:60], steps=steps, kind="auto", goal=goal))

    # ------------------------------------------------------------------ teach mode
    async def teach(self, intent: Intent, ctx: TaskContext, *, deterministic: bool = True, origin: str = "router") -> Outcome:
        if (o := self.offline(ctx)) is not None:
            return o
        name = (intent.params.get("name") or "").strip() or time.strftime("skill %H%M")
        if self.recording:
            return Outcome(False, tr(ctx, f"Pehle se '{self.recording['name']}' record ho raha hai. 'save karo' ya 'cancel recording' bolo.",
                                     f"Already recording '{self.recording['name']}'. Say 'save' or 'cancel recording'."))
        await self.call(ctx, "rec.start", {"name": name[:80]}, origin=origin)
        self.recording = {"name": name, "started": time.time()}
        self.bus.emit("recording", on=True, name=name)
        return Outcome(True, tr(ctx, f"Theek hai, sikhao! Phone pe '{name}' karke dikhao, phir bolo 'save karo' "
                                     "(ya phone ki notification mein Save dabao).",
                                f"Okay, show me! Do '{name}' on the phone, then say 'save' (or tap Save in the notification)."))

    async def save_recording(self, intent: Intent, ctx: TaskContext, *, deterministic: bool = True,
                             origin: str = "router") -> Outcome:
        if (o := self.offline(ctx)) is not None:
            return o
        res = await self.call(ctx, "rec.stop", {}, origin=origin)
        rec, self.recording = self.recording, None
        self.bus.emit("recording", on=False)
        steps = [s for s in (res.get("steps") or []) if s.get("a") in REPLAYABLE]
        name = (intent.params.get("name") or (rec or {}).get("name") or res.get("name") or "").strip() or time.strftime("skill %H%M")
        if not steps:
            return Outcome(False, tr(ctx, "Kuch record nahi hua. Dobara 'sikho' bolke try karo.",
                                     "Nothing was recorded. Try teaching it again."))
        old = self.find(name)
        skill = Skill(name=name, steps=steps, package=res.get("package"), id=old.id if old else uuid.uuid4().hex[:10])
        self.save(skill)
        return Outcome(True, tr(ctx, f"'{name}' seekh liya ({len(steps)} steps). Ab bas bolo '{name} chalao'.",
                                f"Learned '{name}' ({len(steps)} steps). Just say 'run {name}'."), {"skill": asdict(skill)})

    async def cancel_recording(self, intent: Intent, ctx: TaskContext, *, deterministic: bool = True,
                               origin: str = "router") -> Outcome:
        if self.phone.connected:
            try:
                await self.call(ctx, "rec.stop", {"cancel": True}, origin=origin)
            except PhoneError:
                pass
        self.recording = None
        self.bus.emit("recording", on=False)
        return Outcome(True, tr(ctx, "Recording cancel kar di.", "Recording cancelled."))

    # ------------------------------------------------------------------ replay
    async def _snapshot(self, ctx: TaskContext) -> dict:
        return await self.call(ctx, "ui.snapshot", {"maxElements": 200}, origin="skill", timeout=10)

    @staticmethod
    def _score(e: dict, s: dict) -> int:
        score = 0
        if s.get("text") and e.get("text") == s["text"]:
            score += 3
        if s.get("desc") and e.get("desc") == s["desc"]:
            score += 3
        if s.get("res") and e.get("res") and (e["res"] == s["res"] or s["res"].endswith("/" + e["res"]) or e["res"].endswith(s["res"])):
            score += 2
        if score and "click" in (e.get("flags") or []):
            score += 1
        if score and s.get("role") and e.get("role") == s["role"]:
            score += 1
        return score

    async def _find_target(self, ctx: TaskContext, s: dict) -> tuple[dict, dict] | None:
        snap = await self._snapshot(ctx)
        best = max(((self._score(e, s), e) for e in snap.get("elements") or []), key=lambda x: x[0], default=(0, None))
        return (snap, best[1]) if best[0] >= 2 and best[1] is not None else None

    async def _tap(self, ctx: TaskContext, s: dict) -> None:
        label = (s.get("text") or s.get("desc") or "").strip()
        if label:
            w = await self.call(ctx, "ui.wait", {"text": label[:120], "timeoutMs": 5000}, origin="skill", timeout=8)
            if not w.get("matched"):
                await self.call(ctx, "ui.scroll_to", {"text": label[:120], "maxScrolls": 6}, origin="skill", timeout=20)
        found = await self._find_target(ctx, s)
        if found is not None:
            snap, e = found
            await self.call(ctx, "ui.tap", {"snapshotId": snap["snapshotId"], "elementId": e["id"]}, origin="skill")
            return
        if label:
            await self.call(ctx, "ui.tap_text", {"text": label[:120], "exact": True}, origin="skill")
            return
        b = s.get("b")
        if b and len(b) == 4:
            await self.call(ctx, "ui.tap", {"x": (b[0] + b[2]) // 2, "y": (b[1] + b[3]) // 2}, origin="skill")
            return
        raise PhoneError("target.not_found", "recorded element has no label")

    async def _type(self, ctx: TaskContext, s: dict, text: str) -> None:
        params: dict = {"text": text, "clear": True, "submit": bool(s.get("submit"))}
        if s.get("res") or s.get("hint"):
            snap = await self._snapshot(ctx)
            for e in snap.get("elements") or []:
                if "edit" not in (e.get("flags") or []):
                    continue
                if (s.get("res") and e.get("res") and (s["res"].endswith(e["res"]) or e["res"].endswith(s["res"]))) or \
                        (s.get("hint") and s["hint"] == e.get("hint")):
                    params.update(snapshotId=snap["snapshotId"], elementId=e["id"])
                    break
        await self.call(ctx, "ui.type", params, origin="skill")

    async def replay(self, skill: Skill, ctx: TaskContext, arg: str | None = None) -> tuple[bool, int, str]:
        """-> (ok, index of the failing/last step, error)."""
        param_i = skill.param_step if arg else None
        for i, s in enumerate(skill.steps):
            if ctx.is_cancelled:
                return False, i, "cancelled"
            a = s.get("a")
            self.bus.emit("skill_step", taskId=ctx.task_id, skill=skill.name, n=i + 1, total=len(skill.steps),
                          step=describe_step(s))
            try:
                if a == "open":
                    if s.get("package"):
                        await self.call(ctx, "app.open", {"package": s["package"]}, origin="skill")
                    else:
                        o = await self.app.actions.open_app(ctx, s.get("label") or "", origin="skill")
                        if not o.ok:
                            return False, i, o.say
                    await asyncio.sleep(self.open_pause)
                elif a == "tap":
                    await self._tap(ctx, s)
                elif a == "type":
                    await self._type(ctx, s, arg if (i == param_i and arg) else str(s.get("text") or ""))
                elif a == "scroll":
                    await self.call(ctx, "ui.scroll", {"direction": s.get("dir") or "down"}, origin="skill")
                elif a == "find":
                    await self.call(ctx, "ui.scroll_to", {"text": str(s.get("text") or "")[:120], "direction": s.get("dir") or "down",
                                                          "maxScrolls": 10}, origin="skill", timeout=30)
                elif a in ("back", "home"):
                    await self.call(ctx, "device.global", {"action": a}, origin="skill")
                elif a == "key":
                    await self.call(ctx, "ui.key", {"key": s.get("key") or "enter"}, origin="skill")
                elif a == "wait":
                    await asyncio.sleep(max(0.3, min(5.0, float(s.get("seconds") or 1))))
                    continue
            except PhoneError as e:
                if e.code in ("device.offline", "policy.stopped", "policy.blocked_app", "device.locked", "action.uncertain"):
                    raise
                return False, i, f"{e.code}: {e.message}"
            await asyncio.sleep(self.pause)
        return True, len(skill.steps), ""

    async def run(self, skill: Skill, ctx: TaskContext, arg: str | None = None) -> Outcome:
        if (o := self.offline(ctx)) is not None:
            return o
        ok, idx, err = await self.replay(skill, ctx, arg)
        skill.runs += 1
        skill.last_run = time.time()
        if ok:
            skill.fails = 0
            self.save(skill)
            return Outcome(True, tr(ctx, f"'{skill.name}' ho gaya ({len(skill.steps)} steps).",
                                    f"Done: '{skill.name}' ({len(skill.steps)} steps)."), {"skill": skill.id})
        skill.fails += 1
        self.save(skill)
        if ctx.is_cancelled:
            return Outcome(False, tr(ctx, "Ruk gaya.", "Stopped."))
        if not (self.cfg.privacy.cloud_llm and self.app.gateway.role_ready("planner")):
            return Outcome(False, tr(ctx, f"'{skill.name}' step {idx + 1} ({describe_step(skill.steps[idx])}) pe atak gaya: {err}",
                                     f"'{skill.name}' got stuck at step {idx + 1} ({describe_step(skill.steps[idx])}): {err}"))
        # hand the rest to the agent, which continues from the current screen
        rest = "; ".join(describe_step(s) for s in skill.steps[idx:])
        goal = skill.goal or f"Finish the task '{skill.name}' on the phone"
        if arg:
            goal += f" (use '{arg}' as the text to type)"
        return Outcome(True, "", followup_goal=goal,
                       followup_hint=f"A recorded replay stopped at step {idx + 1} ({err}). Remaining recorded steps: {rest}")

    # ------------------------------------------------------------------ intents
    async def run_intent(self, intent: Intent, ctx: TaskContext, *, deterministic: bool = True, origin: str = "router") -> Outcome:
        name = intent.params.get("name") or ""
        skill = self.skills.get(intent.params.get("id") or "") or self.find(name)
        if skill is None:
            return Outcome(False, tr(ctx, f"'{name}' naam ki koi skill nahi hai. 'sikho: {name}' bolke sikhao.",
                                     f"No skill called '{name}'. Teach it with 'learn {name}'."))
        return await self.run(skill, ctx, intent.params.get("arg"))

    async def list_intent(self, intent: Intent, ctx: TaskContext, *, deterministic: bool = True, origin: str = "router") -> Outcome:
        taught = [s for s in self.list() if s.kind == "taught"]
        auto = [s for s in self.list() if s.kind == "auto"]
        if not taught and not auto:
            return Outcome(True, tr(ctx, "Abhi koi skill nahi hai. Bolo 'sikho: <naam>' aur phone pe karke dikhao.",
                                    "No skills yet. Say 'learn <name>' and show me on the phone."))
        text = tr(ctx, "Skills: ", "Skills: ") + (", ".join(s.name for s in taught) or "—")
        if auto:
            text += tr(ctx, f". Aur {len(auto)} khud seekhe hue routes.", f". Plus {len(auto)} routes I learned myself.")
        return Outcome(True, text, {"skills": [asdict(s) for s in self.list()]})

    async def delete_intent(self, intent: Intent, ctx: TaskContext, *, deterministic: bool = True, origin: str = "router") -> Outcome:
        skill = self.find(intent.params.get("name") or "")
        if skill is None:
            return Outcome(False, tr(ctx, "Aisi koi skill nahi mili.", "I couldn't find that skill."))
        self.delete(skill.id)
        return Outcome(True, tr(ctx, f"'{skill.name}' skill delete kar di.", f"Deleted the skill '{skill.name}'."))
