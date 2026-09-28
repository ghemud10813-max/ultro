"""Deeper phone control: find my phone, where is my phone, call control, now playing,
screen time, device info and system settings (auto-rotate, screen timeout, haptics)."""

from __future__ import annotations

from nixin.features.base import Feature, Intent, Outcome, TaskContext, tr


def fmt_ms(ms: int | float | None, lang: str) -> str:
    total_min = int((ms or 0) // 60000)
    h, m = divmod(total_min, 60)
    if lang == "english":
        return (f"{h}h {m}m" if h else f"{m} min") if total_min else "under a minute"
    return (f"{h} ghante {m} minute" if h else f"{m} minute") if total_min else "ek minute se kam"


def fmt_bytes(n: int | float | None) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB", "MB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class PhoneExtras(Feature):
    name = "phone_extras"

    def handlers(self):
        return {"find_phone": self.find_phone, "locate_phone": self.locate, "call_control": self.call_control,
                "now_playing": self.now_playing, "usage": self.usage, "device_info": self.device_info,
                "device_setting": self.device_setting}

    async def find_phone(self, intent: Intent, ctx: TaskContext, *, deterministic: bool = True, origin: str = "router") -> Outcome:
        if (o := self.offline(ctx)) is not None:
            return o
        if intent.params.get("stop"):
            await self.call(ctx, "device.ring", {"stop": True}, origin=origin)
            return Outcome(True, tr(ctx, "Ringing band kar di.", "Stopped ringing."))
        secs = int(intent.params.get("seconds") or 30)
        res = await self.call(ctx, "device.ring", {"seconds": secs}, origin=origin)
        return Outcome(True, tr(ctx, f"Phone {secs} second tak full awaaz mein baj raha hai (silent pe bhi). "
                                     "Mil jaye to phone pe Stop dabao ya bolo 'ringing band karo'.",
                                f"Your phone is ringing at full volume for {secs}s (even on silent). "
                                "Tap Stop on it or say 'stop ringing'."), res)

    async def locate(self, intent: Intent, ctx: TaskContext, *, deterministic: bool = True, origin: str = "router") -> Outcome:
        if (o := self.offline(ctx)) is not None:
            return o
        res = await self.call(ctx, "device.location", {"timeoutMs": 12000}, origin=origin, timeout=16)
        lat, lon = res.get("lat"), res.get("lon")
        if lat is None or lon is None:
            return Outcome(False, tr(ctx, "Location nahi mil payi.", "Couldn't get the location."))
        link = f"https://maps.google.com/?q={lat:.6f},{lon:.6f}"
        acc = res.get("accuracy")
        acc_txt = f" (±{acc:.0f} m)" if isinstance(acc, (int, float)) else ""
        self.bus.emit("phone_location", lat=lat, lon=lon, accuracy=acc, link=link)
        return Outcome(True, tr(ctx, f"Phone yahan hai{acc_txt}: {link}", f"Your phone is here{acc_txt}: {link}"),
                       {**res, "link": link})

    async def call_control(self, intent: Intent, ctx: TaskContext, *, deterministic: bool = True, origin: str = "router") -> Outcome:
        if (o := self.offline(ctx)) is not None:
            return o
        action = intent.params.get("action") or "end"
        res = await self.call(ctx, "call.control", {"action": action}, origin=origin)
        hi = {"answer": "Call utha liya.", "end": "Call kaat diya.", "speaker_on": "Speaker on.", "speaker_off": "Speaker band.",
              "mute": "Mic mute kar diya.", "unmute": "Mic unmute kar diya."}
        en = {"answer": "Answered the call.", "end": "Call ended.", "speaker_on": "Speaker on.", "speaker_off": "Speaker off.",
              "mute": "Microphone muted.", "unmute": "Microphone unmuted."}
        return Outcome(True, tr(ctx, hi.get(action, "Ho gaya."), en.get(action, "Done.")), res)

    async def now_playing(self, intent: Intent, ctx: TaskContext, *, deterministic: bool = True, origin: str = "router") -> Outcome:
        if (o := self.offline(ctx)) is not None:
            return o
        res = await self.call(ctx, "media.now_playing", {}, origin=origin)
        title = res.get("title")
        if not title:
            return Outcome(True, tr(ctx, "Abhi kuch nahi chal raha.", "Nothing is playing right now."), res)
        who = f" — {res['artist']}" if res.get("artist") else ""
        app = f" ({res['app']})" if res.get("app") else ""
        paused = res.get("state") == "paused"
        return Outcome(True, tr(ctx, f"{'Ruka hua hai' if paused else 'Chal raha hai'}: {title}{who}{app}.",
                                f"{'Paused' if paused else 'Playing'}: {title}{who}{app}."), res)

    async def usage(self, intent: Intent, ctx: TaskContext, *, deterministic: bool = True, origin: str = "router") -> Outcome:
        if (o := self.offline(ctx)) is not None:
            return o
        period = intent.params.get("period") or "today"
        res = await self.call(ctx, "usage.stats", {"period": period, "limit": 8}, origin=origin)
        apps = res.get("apps") or []
        total = res.get("totalMs") or sum(a.get("ms") or 0 for a in apps)
        when = {"today": ("Aaj", "Today"), "yesterday": ("Kal", "Yesterday"), "week": ("Is hafte", "This week")}[period]
        top = ", ".join(f"{a.get('label') or a.get('package')} {fmt_ms(a.get('ms'), ctx.lang)}" for a in apps[:3])
        text = tr(ctx, f"{when[0]} phone {fmt_ms(total, ctx.lang)} chala.", f"{when[1]} you used your phone for {fmt_ms(total, ctx.lang)}.")
        if top:
            text += tr(ctx, f" Sabse zyada: {top}.", f" Top apps: {top}.")
        if res.get("unlocks"):
            text += tr(ctx, f" {res['unlocks']} baar unlock kiya.", f" Unlocked {res['unlocks']} times.")
        return Outcome(True, text, res)

    async def device_info(self, intent: Intent, ctx: TaskContext, *, deterministic: bool = True, origin: str = "router") -> Outcome:
        if (o := self.offline(ctx)) is not None:
            return o
        res = await self.call(ctx, "device.info", {}, origin=origin)
        what = intent.params.get("what") or "all"
        st, ram, bat, net = (res.get("storage") or {}), (res.get("ram") or {}), (res.get("battery") or {}), (res.get("network") or {})
        storage = tr(ctx, f"Storage {fmt_bytes(st.get('freeBytes'))} khaali hai ({fmt_bytes(st.get('totalBytes'))} mein se)",
                     f"{fmt_bytes(st.get('freeBytes'))} free of {fmt_bytes(st.get('totalBytes'))}")
        if what == "storage":
            return Outcome(True, storage + ".", res)
        battery = ""
        if bat:
            temp = f", {bat['temperatureC']:.0f}°C" if isinstance(bat.get("temperatureC"), (int, float)) else ""
            battery = tr(ctx, f"Battery {bat.get('level', '?')}%{temp}, health {bat.get('health', '?')}",
                         f"battery {bat.get('level', '?')}%{temp}, health {bat.get('health', '?')}")
        if what == "battery":
            return Outcome(True, (battery or "?") + ".", res)
        network = net.get("type") or "?"
        if net.get("ssid"):
            network += f" ({net['ssid']})"
        if what == "network":
            return Outcome(True, tr(ctx, f"Network: {network}.", f"Network: {network}."), res)
        parts = [f"{res.get('manufacturer', '')} {res.get('model', '')}".strip() + f", Android {res.get('android', '?')}", storage]
        if ram:
            parts.append(f"RAM {fmt_bytes(ram.get('availBytes'))} free / {fmt_bytes(ram.get('totalBytes'))}")
        if battery:
            parts.append(battery)
        parts.append(f"network {network}")
        return Outcome(True, ". ".join(p for p in parts if p) + ".", res)

    async def device_setting(self, intent: Intent, ctx: TaskContext, *, deterministic: bool = True, origin: str = "router") -> Outcome:
        if (o := self.offline(ctx)) is not None:
            return o
        name, value = intent.params["name"], intent.params["value"]
        res = await self.call(ctx, "device.setting", {"name": name, "value": value}, origin=origin)
        if name == "screen_timeout":
            secs = int(value)
            human = f"{secs // 60} minute" if secs >= 60 and secs % 60 == 0 else f"{secs} second"
            return Outcome(True, tr(ctx, f"Screen timeout {human} kar diya.", f"Screen timeout set to {human}s."), res)
        label = {"auto_rotate": "Auto rotate", "haptics": "Haptic feedback"}.get(name, name)
        state = tr(ctx, "on" if value else "band", "on" if value else "off")
        return Outcome(True, tr(ctx, f"{label} {state} kar diya.", f"{label} turned {state}."), res)
