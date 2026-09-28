"""Weather ("kal barish hogi?", "Delhi ka mausam") and the daily briefing ("good morning" →
time, weather, phone battery, notifications, yesterday's screen time, today's reminders)."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta

from nixin.features.base import Feature, Intent, Outcome, TaskContext, tr
from nixin.features.phone_extras import fmt_ms
from nixin.features.weather import Place, Weather, WeatherError
from nixin.link.protocol import PhoneError


class WeatherFeature(Feature):
    name = "weather"
    local = frozenset({"weather", "briefing"})

    def __init__(self, app, weather: Weather | None = None) -> None:
        super().__init__(app)
        self.weather = weather or Weather(app.http)
        self._phone_place: tuple[float, Place] | None = None

    def handlers(self):
        return {"weather": self.handle_weather, "briefing": self.handle_briefing}

    async def place(self, ctx: TaskContext, city: str | None) -> Place:
        city = (city or "").strip() or self.cfg.assistant.city
        if city:
            return await self.weather.geocode(city)
        if self._phone_place and time.time() - self._phone_place[0] < 3600:
            return self._phone_place[1]
        if self.phone.connected:
            try:
                loc = await self.call(ctx, "device.location", {"timeoutMs": 8000}, timeout=12)
                if loc.get("lat") is not None:
                    p = Place(tr(ctx, "aapke yahan", "your area"), float(loc["lat"]), float(loc["lon"]))
                    self._phone_place = (time.time(), p)
                    return p
            except PhoneError:
                pass
        raise WeatherError(tr(ctx, "Kaunse shehar ka? nixin.toml mein [assistant] city set karo ya phone pe location allow karo.",
                              "Which city? Set [assistant] city in nixin.toml or allow location on the phone."))

    async def handle_weather(self, intent: Intent, ctx: TaskContext, *, deterministic: bool = True,
                             origin: str = "router") -> Outcome:
        try:
            place = await self.place(ctx, intent.params.get("city"))
            text, data = await self.weather.report(place, intent.params.get("when") or "now", ctx.lang)
        except WeatherError as e:
            return Outcome(False, str(e))
        q = intent.params.get("question")
        if q == "rain":
            daily = data.get("daily") or {}
            idx = 1 if intent.params.get("when") == "tomorrow" else 0
            probs = daily.get("precipitation_probability_max") or []
            p = probs[idx] if idx < len(probs) else None
            if p is not None:
                day = tr(ctx, "Kal" if idx else "Aaj", "Tomorrow" if idx else "Today")
                verdict = (tr(ctx, "haan, baarish ho sakti hai — chhata le jaana", "yes, rain is likely — take an umbrella")
                           if p >= 50 else tr(ctx, "shayad halki baarish", "maybe a little rain") if p >= 25
                           else tr(ctx, "baarish ke chances kam hain", "rain is unlikely"))
                text = f"{day} {place.name}: {verdict} ({p:.0f}%)."
        return Outcome(True, text, {"place": place.name, "lat": place.lat, "lon": place.lon})

    # ------------------------------------------------------------------ briefing
    async def briefing_text(self, ctx: TaskContext) -> str:
        now = datetime.now()
        lang = ctx.lang
        greet = (tr(lang, "Good morning!", "Good morning!") if now.hour < 12 else
                 tr(lang, "Good afternoon!", "Good afternoon!") if now.hour < 17 else tr(lang, "Good evening!", "Good evening!"))
        clock = now.strftime("%I:%M %p").lstrip("0")
        parts = [greet + " " + tr(lang, f"Aaj {now.strftime('%A, %d %B')} hai, {clock}.",
                                  f"It's {now.strftime('%A, %d %B')}, {clock}.")]

        async def weather() -> str:
            try:
                place = await self.place(ctx, None)
                text, _ = await asyncio.wait_for(self.weather.report(place, "today", lang), 10)
                return text
            except (WeatherError, TimeoutError):
                return ""

        async def phone_bits() -> list[str]:
            if not self.phone.connected:
                return [tr(lang, "Phone abhi connected nahi hai.", "Your phone isn't connected.")]
            out: list[str] = []
            try:
                st = await self.phone.refresh_status()
                b = st.get("battery") or {}
                if b.get("level") is not None:
                    out.append(tr(lang, f"Phone ki battery {b['level']}%.", f"Phone battery {b['level']}%."))
            except PhoneError:
                pass
            notifs = getattr(self.app, "notifications", None)
            try:
                res = await self.call(ctx, "notif.list", {"limit": 20})
                items = res.get("notifications") or []
                if items and notifs is not None:
                    out.append(await notifs.summarize(items, lang))
                elif not items:
                    out.append(tr(lang, "Koi nayi notification nahi.", "No new notifications."))
            except PhoneError:
                pass
            try:
                u = await self.call(ctx, "usage.stats", {"period": "yesterday", "limit": 3})
                total = u.get("totalMs")
                if total:
                    top = (u.get("apps") or [{}])[0]
                    out.append(tr(lang, f"Kal phone {fmt_ms(total, lang)} chala, sabse zyada {top.get('label', '?')}.",
                                  f"Yesterday's screen time: {fmt_ms(total, lang)}, mostly {top.get('label', '?')}."))
            except PhoneError:
                pass
            return out

        def upcoming() -> str:
            engine = getattr(self.app, "routines", None)
            if engine is None:
                return ""
            end = now + timedelta(hours=14)
            items: list[tuple[datetime, str]] = []
            for r in engine.list():
                t = r.trigger
                if not r.enabled:
                    continue
                if t.type == "once" and t.when and now.timestamp() <= t.when <= end.timestamp():
                    items.append((datetime.fromtimestamp(t.when), r.name))
                elif t.type == "time" and t.at and (not t.days or now.isoweekday() in t.days):
                    hh, mm = (int(x) for x in t.at.split(":"))
                    at = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                    if now <= at <= end:
                        items.append((at, r.name))
            if not items:
                return ""
            items.sort()
            lst = ", ".join(f"{d.strftime('%I:%M %p').lstrip('0')} {n}" for d, n in items[:4])
            return tr(lang, f"Aaj aage: {lst}.", f"Coming up: {lst}.")

        w, pb = await asyncio.gather(weather(), phone_bits())
        if w:
            parts.append(w)
        parts += pb
        up = upcoming()
        if up:
            parts.append(up)
        return " ".join(p for p in parts if p)

    async def handle_briefing(self, intent: Intent, ctx: TaskContext, *, deterministic: bool = True,
                              origin: str = "router") -> Outcome:
        return Outcome(True, await self.briefing_text(ctx))
