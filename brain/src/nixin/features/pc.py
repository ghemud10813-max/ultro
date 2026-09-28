"""Intent handler for controlling the PC ("PC lock karo", "laptop ka volume kam karo",
"PC ka screenshot bhejo", "computer pe youtube kholo", "PC ka clipboard phone pe bhejo")."""

from __future__ import annotations

import time

from nixin.features.base import Feature, Intent, Outcome, TaskContext, tr
from nixin.features.pc_control import PcControl, PcError
from nixin.link.protocol import PhoneError


class PcFeature(Feature):
    name = "pc"
    local = frozenset({"pc"})

    def __init__(self, app, pc: PcControl | None = None) -> None:
        super().__init__(app)
        self.pc = pc or PcControl()

    def handlers(self):
        return {"pc": self.handle}

    async def handle(self, intent: Intent, ctx: TaskContext, *, deterministic: bool = True, origin: str = "router") -> Outcome:
        p = intent.params
        a = p.get("action", "")
        try:
            return await self._do(a, p, ctx, deterministic)
        except PcError as e:
            return Outcome(False, tr(ctx, f"PC pe nahi ho paya: {e}", f"Couldn't do that on the PC: {e}"))
        except ModuleNotFoundError as e:
            return Outcome(False, tr(ctx, f"Iske liye PC pe '{e.name}' install karna hoga (pip install nixin[voice]).",
                                     f"That needs '{e.name}' on the PC (pip install nixin[voice])."))

    async def _confirm(self, ctx: TaskContext, question: str) -> bool:
        if ctx.source in ("routine", "plugin") and ctx.trusted:
            return True
        ans = await self.app.gate.ask(question, kind="confirm", task_id=ctx.task_id, source=ctx.source,
                                      timeout=self.cfg.assistant.confirm_timeout_seconds)
        return ans == "yes"

    async def _do(self, a: str, p: dict, ctx: TaskContext, deterministic: bool) -> Outcome:
        pc = self.pc
        if a == "lock":
            await pc.lock()
            return Outcome(True, tr(ctx, "PC lock kar diya.", "PC locked."))
        if a == "sleep":
            if ctx.spoken and not await self._confirm(ctx, tr(ctx, "PC ko sleep mein daalun?", "Put the PC to sleep?")):
                return Outcome(False, tr(ctx, "Theek hai, nahi kiya.", "Okay, cancelled."), code="declined")
            await pc.sleep()
            return Outcome(True, tr(ctx, "PC sleep mein ja raha hai.", "PC is going to sleep."))
        if a in ("shutdown", "restart"):
            restart = a == "restart"
            what = tr(ctx, "restart" if restart else "band", "restart" if restart else "shut down")
            if not await self._confirm(ctx, tr(ctx, f"PC {what} karun? (1 minute baad hoga)",
                                               f"{what.capitalize()} the PC? (in 1 minute)")):
                return Outcome(False, tr(ctx, "Theek hai, nahi kiya.", "Okay, cancelled."), code="declined")
            await pc.shutdown(restart=restart, delay_seconds=int(p.get("delay") or 60))
            return Outcome(True, tr(ctx, f"PC 1 minute mein {what} hoga. Rokna ho to bolo 'shutdown cancel karo'.",
                                    f"The PC will {what} in 1 minute. Say 'cancel shutdown' to stop it."))
        if a == "cancel_shutdown":
            await pc.cancel_shutdown()
            return Outcome(True, tr(ctx, "Shutdown cancel kar diya.", "Shutdown cancelled."))
        if a == "volume":
            mode = p.get("mode") or "up"
            res = await pc.volume(mode, p.get("percent"), int(p.get("steps") or 3))
            if res.endswith("%"):
                return Outcome(True, tr(ctx, f"PC ka volume ab {res} hai.", f"PC volume is now {res}."))
            done_hi = {"up": "badha diya", "down": "kam kar diya", "mute": "mute kar diya", "unmute": "unmute kar diya",
                       "max": "full kar diya", "set": f"{p.get('percent')}% kar diya"}.get(mode, "badal diya")
            done_en = {"up": "turned up", "down": "turned down", "mute": "muted", "unmute": "unmuted",
                       "max": "set to max", "set": f"set to {p.get('percent')}%"}.get(mode, "changed")
            return Outcome(True, tr(ctx, f"PC ka volume {done_hi}.", f"PC volume {done_en}."))
        if a == "media":
            await pc.media(p.get("mode") or "toggle")
            return Outcome(True, tr(ctx, "PC pe kar diya.", "Done on the PC."))
        if a == "open":
            res = await pc.open(p["target"])
            return Outcome(True, tr(ctx, f"PC pe {res} khol diya.", f"Opened {res} on the PC."))
        if a == "search":
            await pc.search(p["query"])
            return Outcome(True, tr(ctx, f"PC pe '{p['query']}' search kar diya.", f"Searched '{p['query']}' on the PC."))
        if a == "type":
            await pc.type_text(p["text"])
            return Outcome(True, tr(ctx, "PC pe type kar diya.", "Typed it on the PC."))
        if a == "status":
            st = await pc.status()
            bits = []
            if st.cpu is not None:
                bits.append(f"CPU {st.cpu:.0f}%")
            if st.ram is not None:
                bits.append(f"RAM {st.ram:.0f}%")
            if st.battery is not None:
                bits.append(f"battery {st.battery}%" + (" (charging)" if st.charging else ""))
            text = f"{st.host}: " + (", ".join(bits) if bits else st.os)
            return Outcome(True, text, {"cpu": st.cpu, "ram": st.ram, "battery": st.battery, "charging": st.charging,
                                        "host": st.host, "os": st.os})
        if a == "screenshot":
            img = await pc.screenshot()
            name = time.strftime("PC-screenshot-%Y%m%d-%H%M%S.jpg")
            bridge = getattr(self.app, "bridge", None)
            if bridge is not None and self.phone.connected:
                await bridge.push_bytes(img, name, "image/jpeg", ctx=ctx)
                return Outcome(True, tr(ctx, "PC ka screenshot phone pe bhej diya (Downloads/Nixin).",
                                        "Sent the PC screenshot to your phone (Downloads/Nixin)."))
            path = bridge.save_inbox_bytes(img, name) if bridge is not None else None
            return Outcome(True, tr(ctx, f"Screenshot le liya: {path}", f"Screenshot saved: {path}"))
        if a == "clipboard_to_phone":
            if (o := self.offline(ctx)) is not None:
                return o
            text = await pc.clipboard_get()
            if not text:
                return Outcome(False, tr(ctx, "PC ka clipboard khaali hai.", "The PC clipboard is empty."))
            await self.call(ctx, "clipboard.set", {"text": text[:100000]})
            return Outcome(True, tr(ctx, "PC ka clipboard phone pe copy kar diya.", "Copied the PC clipboard to your phone."))
        if a == "clipboard_from_phone":
            if (o := self.offline(ctx)) is not None:
                return o
            try:
                res = await self.call(ctx, "clipboard.get")
            except PhoneError as e:
                if e.code == "device.unsupported":
                    return Outcome(False, tr(ctx, "Android sirf tab clipboard padhne deta hai jab Nixin app khula ho. "
                                                  "Phone pe text select karke Share → Nixin karo.",
                                             "Android only allows reading the clipboard while the Nixin app is open. "
                                             "Share the text to Nixin from the phone instead."))
                raise
            text = res.get("text") or ""
            if not text:
                return Outcome(False, tr(ctx, "Phone ka clipboard khaali hai.", "The phone clipboard is empty."))
            await pc.clipboard_set(text)
            return Outcome(True, tr(ctx, "Phone ka clipboard PC pe aa gaya.", "Copied the phone clipboard to the PC."))
        return Outcome(False, tr(ctx, "PC pe yeh nahi kar sakta.", "I can't do that on the PC."))
