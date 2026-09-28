"""Router rules for Nixin 2.0 features (no LLM).

Routines & reminders by voice, PC control, weather, briefing, find-my-phone, call control, now playing,
screen time, device info/settings, notification reply/summary/clear, screen reading, teach mode,
routine/skill management and the PC ⇄ phone bridge.

Every rule gets the cleaned text ``c`` (lowercase, wake word/fillers removed), the original text and now.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from nixin.router.intent import Intent
from nixin.router.normalize import strip_wake
from nixin.router.timeparse import ClockTime, parse_clock, parse_duration

_DO = r"(?:karo|kar|kar do|kardo|kar de|karde|kariye|kijiye|karna|krdo|kr do|kro|kr|kar dena|karna)"
_PC = r"(?:pc|laptop|computer|desktop|system)"
_TELL = (r"(?:mujhe\s+)?(?:bata(?:na|o)?(?:\s+(?:dena|do|de))?|batana|bol(?:na|o)?(?:\s+(?:dena|do))?|announce(?:\s+(?:karna|karo|kar dena))?"
         r"|alert(?:\s+(?:karna|karo|kar dena))?|sunao|suna dena|tell me|notify me|let me know|alert me|inform me"
         r"|yaad dila(?:na|o)?(?:\s+dena)?|remind me)")

_WEEKDAYS = {
    1: r"(?:somvar|somwar|monday|mon)", 2: r"(?:mangalvar|mangalwar|tuesday|tue)", 3: r"(?:budhvar|budhwar|wednesday|wed)",
    4: r"(?:guruvar|guruwar|brihaspativar|thursday|thu)", 5: r"(?:shukravar|shukrawar|friday|fri)",
    6: r"(?:shanivar|shaniwar|saturday|sat)", 7: r"(?:ravivar|raviwar|itvar|itwar|sunday|sun)",
}
_RECUR = (r"(?:har\s+roz|roz(?:ana|aana)?|har\s+din|daily|every\s*day|everyday|har\s+(?:raat|subah|shaam|sham|dopahar)"
          r"|every\s+(?:night|morning|evening|afternoon)|weekdays?(?:\s+(?:pe|par|mein|on))?|weekends?(?:\s+(?:pe|par|mein|on))?"
          r"|har\s+hafte|every\s+week|har\s+\w+var|har\s+\w+war|every\s+(?:mon|tues|wednes|thurs|fri|satur|sun)day)")
_TIME_TOKEN = (r"(?:(?:subah|savere|sawere|morning|dopahar|shaam|sham|evening|raat|rat|night)\s+)?"
               r"(?:(?:saade|sade|saadhe|sadhe|sawa|sava|paune)\s+)?\d{1,2}(?:\s*[:.]\s*\d{2})?\s*(?:baje|bje|am|pm|a\.m\.?|p\.m\.?|o'?clock)"
               r"(?:\s+\d{1,2}\s*(?:minute|min))?")
_APPS_HINT = {"whatsapp", "instagram", "telegram", "gmail", "mail", "sms", "messages", "facebook", "snapchat", "twitter",
              "linkedin", "youtube", "signal", "discord", "slack", "teams", "outlook", "truecaller"}


def _english(text: str) -> bool:
    return not re.search(r"\b(?:jab|ho|hai|karo|dena|bata|bol|ka|ki|ke|ko|se|pe|kam|aaye|aaya)\b", text)


def _route_action(text: str, now: datetime) -> Intent | None:
    from nixin.router.router import _route_one

    return _route_one(text, now)


def _split_actions(text: str) -> list[str]:
    from nixin.router.router import _SPLIT

    return [p.strip(" ,.") for p in _SPLIT.split(text) if p.strip(" ,.")]


def _days(c: str) -> list[int]:
    if re.search(r"\bweekdays?\b", c):
        return [1, 2, 3, 4, 5]
    if re.search(r"\bweekends?\b", c):
        return [6, 7]
    return [d for d, pat in _WEEKDAYS.items() if re.search(rf"\b{pat}\b", c)]


def _say_action(act: str) -> str | None:
    """'yaad dilana ki dawai leni hai' -> 'dawai leni hai' (text to announce), else None."""
    m = re.match(rf"^{_TELL}\s*(?:ki|that|to|:)?\s*(?P<msg>.*)$", act, flags=re.I)
    if m:
        return m.group("msg").strip(" .") or ""
    m = re.match(r"^(?P<msg>.+?)\s+(?:ka|ki|ke liye|ke)\s+(?:reminder|yaad)(?:\s+(?:do|dena|dilana|lagao|laga do))?$", act, flags=re.I) \
        or re.match(r"^(?:reminder|yaad dilana)\s*[:,-]?\s*(?P<msg>.+)$", act, flags=re.I)
    if m:
        return m.group("msg").strip(" .")
    return None


def recurring_alarm_days(c: str) -> list[int] | None:
    """For "roz 6 baje ka alarm" / "har somvar 7 baje alarm": Android Calendar days (1=Sunday..7=Saturday)."""
    if not re.search(rf"\b{_RECUR}\b", c):
        return None
    iso = _days(c) or [1, 2, 3, 4, 5, 6, 7]
    return sorted(d % 7 + 1 for d in iso)


def habit_hour(ct: ClockTime, text: str) -> int:
    """Hour for a recurring time said without AM/PM: 5-11 -> morning, 12-4 -> afternoon."""
    if ct.explicit_meridiem or re.search(r"\b(?:subah|savere|morning|shaam|sham|evening|raat|night|dopahar|am|pm)\b", text):
        return ct.hour
    h12 = ct.hour % 12
    return h12 if 5 <= h12 <= 11 else (12 if h12 == 0 else h12 + 12)


# ------------------------------------------------------------------ routines by voice
def r_routine(c: str, orig: str, now: datetime) -> Intent | None:
    return _event_routine(c, orig, now) or _time_routine(c, orig, now)


def _time_routine(c: str, orig: str, now: datetime) -> Intent | None:
    rec = re.search(rf"\b{_RECUR}\b", c)
    alarmish = re.search(r"\b(?:alarm|uthana|utha dena|jagana|jaga dena|wake me)\b", c)
    if rec is None:
        # one-off scheduled command: "raat 11 baje phone silent kar dena", "at 11 pm turn on dnd"
        m = re.match(rf"^(?:at\s+)?(?P<time>{_TIME_TOKEN})\s+(?:pe\s+|par\s+|ko\s+)?(?P<act>.+)$", c)
        if not m or alarmish or re.search(r"\b(?:yaad|remind|reminder)\b", c):
            return None
        act = m.group("act")
        it = _route_action(act, now)
        if it is None or it.kind in ("clarify", "chat", "alarm", "timer", "reminder", "routine_add", "cancel"):
            return None
        ct = parse_clock(m.group("time"), now)
        if ct is None:
            return None
        when = ct.next_occurrence(now)
        return Intent("routine_add", {"name": f"{when.strftime('%H:%M')} — {act[:30]}",
                                      "trigger": {"type": "once", "when": when.timestamp()}, "actions": [act]}, orig)
    if alarmish:
        return None  # "roz 6 baje ka alarm" -> repeating alarm on the phone
    # "<rec> <time> <action>"  or  "<action> <rec> <time>"
    m = re.match(rf"^(?P<pre>.*?\b{_RECUR}\b.*?)\s*(?:at\s+)?(?P<time>{_TIME_TOKEN})\s+(?:pe\s+|par\s+|ko\s+)?(?P<act>.+)$", c) \
        or re.match(rf"^(?P<act>.+?)\s+(?P<pre>\b{_RECUR}\b.*?)\s*(?:at\s+)?(?P<time>{_TIME_TOKEN})$", c)
    if not m:
        if re.match(rf"^{_RECUR}\b", c):
            return Intent("clarify", {"question": "Kitne baje karna hai?"}, orig)
        return None
    ct = parse_clock(f"{m.group('pre')} {m.group('time')}", now)
    if ct is None:
        return None
    ct = ClockTime(habit_hour(ct, m.group("pre") + " " + m.group("time")), ct.minute, True, None)
    act = m.group("act").strip(" ,.")
    msg = _say_action(act)
    if msg is not None:
        if not msg:
            return Intent("clarify", {"question": "Kya yaad dilana hai?"}, orig)
        actions = [f"notify: {msg}", f"say: Yaad dila raha hoon: {msg}"]
    else:
        actions = _split_actions(act)
    return Intent("routine_add", {"trigger": {"type": "time", "at": f"{ct.hour:02d}:{ct.minute:02d}", "days": _days(c)},
                                  "actions": actions}, orig)


_EVENT_SAY = {
    "battery_low": ("Phone ki battery {level}% reh gayi hai, charger laga lo.", "Phone battery is at {level}%, plug in the charger."),
    "battery_full": ("Phone {level}% charge ho gaya.", "Phone is charged to {level}%."),
    "notification": ("{title} ka {app} pe message: {text}", "{title} on {app}: {text}"),
    "call_incoming": ("{caller} ka call aa raha hai.", "{caller} is calling."),
    "charging": ("Charger lag gaya.", "Charger connected."),
    "unplugged": ("Charger nikal gaya.", "Charger disconnected."),
    "wifi_connected": ("Wi-Fi connect ho gaya {ssid}.", "Wi-Fi connected {ssid}."),
    "wifi_disconnected": ("Wi-Fi disconnect ho gaya.", "Wi-Fi disconnected."),
    "phone_connected": ("Phone connect ho gaya.", "Phone connected."),
    "phone_disconnected": ("Phone disconnect ho gaya.", "Phone disconnected."),
    "unlocked": ("Welcome back!", "Welcome back!"),
    "screen_off": ("Screen band ho gayi.", "Screen off."),
    "screen_on": ("Screen on hui.", "Screen on."),
}


def _condition(cond: str) -> dict | None:
    cond = re.sub(r"\b(?:bhi|mera|meri|mere|my|the|phone ki|phone ka)\b", " ", cond)
    cond = re.sub(r"\s+", " ", cond).strip()
    if re.search(r"\bbattery\b", cond):
        n = re.search(r"\b(\d{1,3})\s*%?", cond)
        if re.search(r"\b(?:full|poori|puri|100)\b", cond) and not re.search(r"\b(?:kam|low|below|neeche|niche|under)\b", cond):
            return {"event": "battery_full", "above": int(n.group(1)) if n and int(n.group(1)) <= 100 else 100}
        if re.search(r"\b(?:kam|low|below|neeche|niche|under|less|khatam|girne|gire)\b", cond) or n:
            return {"event": "battery_low", "below": int(n.group(1)) if n and int(n.group(1)) <= 100 else 20}
        return None
    if re.search(r"\b(?:charger|charging|charge)\b", cond):
        if re.search(r"\b(?:nikal\w*|hata\w*|hate|disconnect\w*|unplug\w*|remove\w*|band)\b", cond):
            return {"event": "unplugged"}
        return {"event": "charging"}
    m = re.match(r"^(?:(?P<who>.+?)\s+(?:ka|ki|ke)\s+)?(?:call|phone)\s*(?:aaye|aaya|aata|aa jaye|aa|kare|karein)?"
                 r"(?:\s+(?:hai|ho|aaye))?$", cond) or re.match(r"^(?P<who>.+?)\s+(?:call|phone)\s+(?:kare|karein|karta|kari)", cond) \
        or re.match(r"^(?:there'?s\s+a\s+|i\s+get\s+a\s+)?call\s+from\s+(?P<who>.+)$", cond) \
        or re.match(r"^(?P<who>.+?)\s+calls(?:\s+me)?$", cond)
    if m and re.search(r"\b(?:call|calls|phone)\b", cond) and not re.search(r"\b(?:wifi|message|msg|notification)\b", cond):
        who = (m.groupdict().get("who") or "").strip()
        return {"event": "call_incoming", **({"contains": who} if who and who not in ("koi", "kisi", "anyone", "someone") else {})}
    if re.search(r"\b(?:message|messages|msg|notification|notifications|whatsapp|sms|text|mail|email)\b", cond):
        who = None
        app = None
        m = re.match(r"^(?P<who>.+?)\s+(?:ka|ki|ke|se)\s+(?:koi\s+)?(?:\w+\s+)?(?:message|msg|notification|whatsapp|sms|text|mail|email)", cond) \
            or re.search(r"\b(?:message|msg|text|mail|email|notification)s?\s+from\s+(?P<who>.+?)(?:\s+(?:on|in)\s+\w+)?$", cond) \
            or re.match(r"^(?P<who>.+?)\s+(?:messages|texts|mails)\s+me$", cond)
        if m:
            who = m.group("who").strip()
        am = re.search(r"\b(?P<app>" + "|".join(sorted(_APPS_HINT)) + r")\b", cond)
        if am:
            app = am.group("app")
        if who and (who in _APPS_HINT or who == app):
            app, who = who, None
        if who and who in ("koi", "kisi", "kisi ka", "any", "anyone", "someone"):
            who = None
        out: dict = {"event": "notification"}
        if app:
            out["app"] = "whatsapp" if app == "whatsapp" else app
        if who:
            out["contains"] = who
        return out
    if re.search(r"\bwi-?fi\b", cond):
        if re.search(r"\b(?:disconnect\w*|band|off|chala jaye|hat)\b", cond):
            return {"event": "wifi_disconnected"}
        return {"event": "wifi_connected"}
    if re.search(r"\b(?:unlock\w*|khol\w*)\b", cond) and re.search(r"\b(?:phone|screen|mobile)\b", cond):
        return {"event": "unlocked"}
    if re.search(r"\b(?:phone|mobile)\s+(?:connect|online)", cond):
        return {"event": "phone_connected"}
    if re.search(r"\b(?:phone|mobile)\s+(?:disconnect|offline)", cond):
        return {"event": "phone_disconnected"}
    if re.search(r"\bscreen\s+(?:off|band)\b", cond):
        return {"event": "screen_off"}
    return None


def _event_routine(c: str, orig: str, now: datetime) -> Intent | None:
    m = re.match(r"^(?:jab|jab bhi|jaise hi|agar|when|whenever|if)\s+(?P<cond>.+?)\s*,?\s+(?:to|toh|tab|then)\s+(?P<act>.+)$", c) \
        or re.match(rf"^(?:jab|jab bhi|jaise hi|when|whenever)\s+(?P<cond>.+?)\s+(?P<act>{_TELL}.*)$", c) \
        or re.match(rf"^(?P<act>{_TELL}|.+?)\s+(?:when|whenever|jab|jab bhi)\s+(?P<cond>.+)$", c)
    if not m:
        return None
    cond = _condition(m.group("cond"))
    if cond is None:
        return None
    act = m.group("act").strip(" ,.")
    english = _english(c)
    msg = _say_action(act)
    if msg is not None:
        if msg:
            actions = [f"say: {msg}"]
        else:
            hi, en = _EVENT_SAY.get(cond["event"], ("{name}", "{name}"))
            actions = [f"say: {en if english else hi}"]
    else:
        actions = _split_actions(act)
        if not actions or _route_action(actions[0], now) is None and len(actions[0].split()) < 2:
            return None
    trig = {"type": "event", **cond}
    return Intent("routine_add", {"trigger": trig, "actions": actions}, orig)


# ------------------------------------------------------------------ reminders
_REMIND = re.compile(r"\b(?:yaad dila\w*|yad dila\w*|remind(?:\s+me)?|reminder)\b")


def r_reminder(c: str, orig: str, now: datetime) -> Intent | None:
    if not _REMIND.search(c) or re.search(rf"\b{_RECUR}\b", c):
        return None
    if re.search(r"\b(?:reminders?)\s+(?:dikhao|batao|list|kya hai|kitne)\b|\b(?:show|list)\s+(?:my\s+)?reminders\b", c):
        return None
    o = strip_wake(orig)
    label = None
    rw = re.search(r"(?:yaad dila\w*|yad dila\w*|remind(?:\s+me)?|reminder(?:\s+(?:set karo|lagao|laga do|do))?)", o, flags=re.I)
    m = re.search(r"(?:\b(?:ki|that|to|about|ke\s+liye)\s+|[:,-]\s*)(?P<label>.+)$", o[rw.end():], flags=re.I) if rw else None
    if m:
        label = m.group("label")
    else:
        m = re.match(r"^(?P<label>.+?)\s+(?:ke liye|ka|ki|about)\s+(?:reminder|yaad)", o, flags=re.I)
        if m:
            label = m.group("label")
    if label:
        label = _strip_time(label)
    # when
    when: datetime | None = None
    if re.search(r"\b(?:baad|bad|later|in\s+\d|in\s+(?:a|an|one|two|five|ten)\b)", c):
        secs = parse_duration(re.sub(r"\b(?:yaad|remind).*$", "", c) or c) or parse_duration(c)
        if secs:
            when = now + timedelta(seconds=secs)
    if when is None:
        ct = parse_clock(c, now)
        if ct is not None:
            when = ct.next_occurrence(now) if not ct.relative else now.replace(hour=ct.hour, minute=ct.minute, second=0)
            if ct.day_hint == "tomorrow" and when.date() == now.date():
                when += timedelta(days=1)
    if when is None:
        return Intent("clarify", {"question": "Kab yaad dilaun?"}, orig)
    if not label:
        label = "Reminder"
    return Intent("reminder", {"text": label[:120], "when": when.timestamp()}, orig)


def _strip_time(label: str) -> str:
    t = label.strip()
    t = re.sub(r"\s*(?:\b(?:at|pe|ko|in)\s+)?(?:\b(?:aaj|kal|today|tomorrow)\s+)?(?:\b(?:subah|shaam|sham|raat|dopahar|morning|evening|night)\s+)?"
               r"\b\d{1,2}(?:\s*[:.]\s*\d{2})?\s*(?:baje|bje|am|pm|a\.m\.?|p\.m\.?|o'?clock)\b(?:\s+(?:ko|pe))?\s*", " ", t, flags=re.I)
    t = re.sub(r"\s*\b(?:in\s+)?\d+\s*(?:minutes?|mins?|minat|ghante|ghanta|hours?|hrs?|seconds?|secs?)\s*(?:baad|bad|later|mein|me)?\b",
               " ", t, flags=re.I)
    t = re.sub(r"\s*\b(?:yaad dila\w*|yad dila\w*|remind me|reminder)\b.*$", "", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" ,.-:")
    return t


# ------------------------------------------------------------------ PC control
def r_pc(c: str, orig: str, now: datetime) -> Intent | None:
    # clipboard between devices (with or without the word PC)
    if re.search(r"\bclipboard\b", c) or re.search(r"\bcopied text\b", c):
        to_phone = re.search(rf"\b(?:{_PC})\s+(?:ka|ki|ke|se|from)\b.*\b(?:phone|mobile)\b|\b(?:phone|mobile)\s+(?:pe|par|me|mein|to)\b", c)
        from_phone = re.search(rf"\b(?:phone|mobile)\s+(?:ka|ki|ke|se|from)\b.*\b(?:{_PC})\b|\b(?:{_PC})\s+(?:pe|par|me|mein|to)\b", c)
        if to_phone and not (from_phone and from_phone.start() < to_phone.start()):
            return Intent("pc", {"action": "clipboard_to_phone"}, orig)
        if from_phone:
            return Intent("pc", {"action": "clipboard_from_phone"}, orig)
    if re.match(r"^(?:shutdown|shut down|restart)\s+(?:cancel|rok|roko|band)(?:\s+(?:karo|kar do|do))?$|^cancel (?:the )?(?:shutdown|restart)$", c):
        return Intent("pc", {"action": "cancel_shutdown"}, orig)
    if not re.search(rf"\b{_PC}\b", c):
        return None
    if re.search(r"\bscreen\s*shot\b|\bscreenshot\b", c):
        return Intent("pc", {"action": "screenshot"}, orig)
    m = re.match(rf"^(?:{_PC}\s+(?:pe|par|me|mein)\s+)?type\s+(?:karo|kar do|karo ki)?\s*(?:{_PC}\s+(?:pe|par)\s+)?[:\-]?\s*(?P<t>.+)$", c) \
        or re.match(rf"^type\s+(?P<t>.+?)\s+on\s+(?:the\s+|my\s+)?{_PC}$", c)
    if m:
        om = re.search(r"type\s+(?:karo|kar do|karo ki)?\s*[:\-]?\s*(.+)$", strip_wake(orig), flags=re.I)
        text = om.group(1) if om else m.group("t")
        text = re.sub(rf"\s+on\s+(?:the\s+|my\s+)?{_PC}$", "", text, flags=re.I)
        return Intent("pc", {"action": "type", "text": text.strip()}, orig)
    if re.search(r"\b(?:shutdown|shut down)\b.*\bcancel\b|\bcancel\b.*\b(?:shutdown|shut down|restart)\b", c):
        return Intent("pc", {"action": "cancel_shutdown"}, orig)
    if re.search(r"\b(?:volume|awaa?z|sound)\b", c):
        from nixin.router.router import _r_volume

        v = _r_volume(re.sub(rf"\b{_PC}\b(?:\s+(?:ka|ki|ke))?", "", c), orig, now)
        if v is None:
            return None
        p = v.params["params"]
        return Intent("pc", {"action": "volume", "mode": p["action"], "percent": p.get("percent"), "steps": p.get("steps", 2)}, orig)
    if re.search(r"\b(?:gaana|gana|song|music|video|media)\b", c) or re.match(rf"^{_PC}\s+(?:pe\s+)?(?:pause|play|next|previous)\b", c):
        if re.search(r"\b(?:next|agla|skip)\b", c):
            return Intent("pc", {"action": "media", "mode": "next"}, orig)
        if re.search(r"\b(?:previous|pichla|prev)\b", c):
            return Intent("pc", {"action": "media", "mode": "previous"}, orig)
        return Intent("pc", {"action": "media", "mode": "toggle"}, orig)
    if re.search(r"\block\b", c):
        return Intent("pc", {"action": "lock"}, orig)
    if re.search(r"\b(?:sleep|sula do|sulao|so jao|hibernate)\b", c):
        return Intent("pc", {"action": "sleep"}, orig)
    if re.search(r"\b(?:restart|reboot)\b", c):
        return Intent("pc", {"action": "restart"}, orig)
    if re.search(r"\b(?:shutdown|shut down|band|off|power off)\b", c) and re.match(rf"^(?:{_PC}|mera {_PC}|my {_PC})\b", c) \
            and not re.search(r"\b(?:screen|monitor)\b", c):
        return Intent("pc", {"action": "shutdown"}, orig)
    if re.search(r"\b(?:status|haal|halat|cpu|ram|memory|battery)\b", c):
        return Intent("pc", {"action": "status"}, orig)
    m = re.match(rf"^(?:{_PC}\s+(?:pe|par|me|mein)\s+)(?P<q>.+?)\s+(?:search|google|dhundo|dhoondo)(?:\s+{_DO})?$", c) \
        or re.match(rf"^(?:search|google)\s+(?P<q>.+?)\s+on\s+(?:the\s+|my\s+)?{_PC}$", c)
    if m:
        return Intent("pc", {"action": "search", "query": m.group("q").strip()}, orig)
    m = re.match(rf"^(?:{_PC}\s+(?:pe|par|me|mein)\s+)(?P<t>.+?)\s+(?:kholo|khol do|khol|open karo|open kar do|open|chalao|chala do|start karo|launch karo)$", c) \
        or re.match(rf"^(?:open|launch|start)\s+(?P<t>.+?)\s+on\s+(?:the\s+|my\s+)?{_PC}$", c)
    if m:
        return Intent("pc", {"action": "open", "target": m.group("t").strip()}, orig)
    return None


# ------------------------------------------------------------------ weather & briefing
_CITY_STOP = {"aaj", "kal", "abhi", "yahan", "bahar", "aaj ka", "kal ka", "kal ki", "aaj ki", "today", "tomorrow", "now",
              "the", "my", "mere", "hamare", "yaha", "idhar", "is", "iss", "abhi ka", "ghar", "outside"}


def r_weather(c: str, orig: str, now: datetime) -> Intent | None:
    if not re.search(r"\b(?:mausam|mosam|mausum|weather|temperature|tapman|taapmaan|forecast|baarish|barish|baarish|rain|raining|"
                     r"chhata|chata|umbrella|garmi|thand|thandi|dhoop|humidity)\b", c):
        return None
    if re.search(r"\b(?:youtube|spotify|gaana|gana|song|sounds|video)\b", c):
        return None
    when = "tomorrow" if re.search(r"\b(?:kal|tomorrow|agle din)\b", c) else ("today" if re.search(r"\b(?:aaj|today)\b", c) else "now")
    question = "rain" if re.search(r"\b(?:baarish|barish|rain|raining|chhata|chata|umbrella)\b", c) else None
    city = None
    m = re.search(r"\b(?P<city>[a-z][a-z ]{1,30}?)\s+(?:ka|ki|ke|mein|me|main)\s+(?:aaj\s+|kal\s+|abhi\s+)?(?:ka\s+|ki\s+)?"
                  r"(?:mausam|mosam|weather|temperature|tapman|forecast|baarish|barish)", c) \
        or re.search(r"\b(?:weather|temperature|forecast|rain)\s+(?:in|of|at|for)\s+(?P<city>[a-z][a-z ]{1,30}?)(?:\s+(?:today|tomorrow|now))?\??$", c) \
        or re.search(r"\b(?:mausam|weather)\s+(?:kaisa|kya)\s+(?:hai|hoga|rahega)\s+(?P<city>[a-z][a-z ]{1,30}?)\s+(?:mein|me)\b", c)
    if m:
        cand = m.group("city").strip()
        cand = re.sub(r"^(?:aaj|kal|abhi|today|tomorrow)\s+", "", cand)
        cand = re.sub(r"\s+(?:aaj|kal|abhi)$", "", cand)
        if cand and cand not in _CITY_STOP and len(cand.split()) <= 3:
            city = cand
    return Intent("weather", {"city": city, "when": when, "question": question}, orig)


def r_briefing(c: str, orig: str, now: datetime) -> Intent | None:
    if re.match(r"^(?:(?:morning|daily|aaj ka|aaj ki|din ka|mera|my)\s+)?(?:briefing|update|summary)"
                r"(?:\s+(?:do|dena|de do|de|sunao|suna do|chahiye|batao|please))?$", c) \
            and not re.match(r"^(?:update|summary)$", c):
        return Intent("briefing", {}, orig)
    if re.match(r"^(?:aaj ka din kaisa hai|aaj kya hai|what'?s my day(?: look like)?|brief me|aaj ka plan kya hai)\??$", c):
        return Intent("briefing", {}, orig)
    return None


# ------------------------------------------------------------------ phone extras
def r_find_phone(c: str, orig: str, now: datetime) -> Intent | None:
    if re.match(r"^(?:ringing|ring|phone ki ringing|alarm)\s+(?:band|stop|bandh|rok)(?:\s+(?:karo|kar do|do))?$|^stop ringing$"
                r"|^phone mil gaya$|^mil gaya(?: phone)?$|^found (?:it|my phone)$", c):
        return Intent("find_phone", {"stop": True}, orig)
    if re.search(r"\b(?:phone|mobile)\b", c) and re.search(r"\b(?:location|lokeshan|gps|kis jagah|kidhar hai location|where is)\b", c) \
            and not re.search(r"\b(?:on|off|band|chalu|settings?)\b", c):
        return Intent("locate_phone", {}, orig)
    if re.match(r"^(?:mera |my )?(?:phone|mobile)\s+(?:kahan|kaha|kidhar|kidhr)\s+(?:hai|gaya|rakha)|"
                r"^(?:mera |my )?(?:phone|mobile)\s+(?:dhundo|dhoondo|dhund do|find karo|kho gaya|nahi mil raha)|"
                r"^find (?:my )?phone$|^(?:phone|mobile)\s+(?:bajao|ring karo|ring kar do)$|^ring (?:my )?phone$", c):
        return Intent("find_phone", {}, orig)
    return None


def r_call_control(c: str, orig: str, now: datetime) -> Intent | None:
    pats = [
        (r"^(?:call|phone)\s+(?:utha|uthao|utha lo|utha do|uthalo|receive karo|pick karo|answer karo|le lo)$|^(?:answer|pick up|receive)(?: the)? call$", "answer"),
        (r"^(?:call|phone)\s+(?:kaat|kaato|kaat do|kato|kat do|cut karo|cut kar do|rakh do|band karo|end karo|disconnect karo|reject karo)$"
         r"|^(?:end|hang up|reject|cut)(?: the)? call$|^hang up$", "end"),
        (r"^speaker\s+(?:on|chalu|pe daalo|pe dalo)(?:\s+karo|\s+kar do)?$|^(?:call\s+)?speaker\s+pe\s+(?:daalo|dalo|karo)$|^(?:turn on|put on) speaker$", "speaker_on"),
        (r"^speaker\s+(?:off|band)(?:\s+karo|\s+kar do)?$|^turn off speaker$", "speaker_off"),
        (r"^(?:mic|microphone|call)\s+mute(?:\s+karo|\s+kar do)?$|^mute (?:the )?(?:mic|microphone|call)$", "mute"),
        (r"^(?:mic|microphone|call)\s+unmute(?:\s+karo|\s+kar do)?$|^unmute (?:the )?(?:mic|microphone|call)$", "unmute"),
    ]
    for pat, action in pats:
        if re.match(pat, c):
            return Intent("call_control", {"action": action}, orig)
    return None


def r_now_playing(c: str, orig: str, now: datetime) -> Intent | None:
    if re.match(r"^(?:ye |yeh |abhi )?(?:kaunsa|kaun sa|konsa|kon sa|kya)\s+(?:gaana|gana|song|music)\s+(?:chal raha|baj raha|hai|play ho raha)"
                r"|^(?:what'?s|what is)\s+(?:playing|this song)|^(?:gaane|gane|song)\s+ka\s+naam\s+(?:kya|batao)|^now playing$", c):
        return Intent("now_playing", {}, orig)
    return None


def r_usage(c: str, orig: str, now: datetime) -> Intent | None:
    if not (re.search(r"\bscreen\s*time\b", c) or re.search(r"\b(?:phone|mobile)\b.*\bkitna\b.*\b(?:chala|chalaya|use|istemal)", c)
            or re.search(r"\bkitna\s+(?:time|samay|der)\s+(?:phone|mobile)\b", c) or re.search(r"\bhow much .*(?:phone|screen)", c)):
        return None
    period = "week" if re.search(r"\b(?:hafte|hafta|week)\b", c) else ("yesterday" if re.search(r"\b(?:kal|yesterday)\b", c) else "today")
    return Intent("usage", {"period": period}, orig)


def r_device_info(c: str, orig: str, now: datetime) -> Intent | None:
    if re.search(r"\bstorage\b|\bspace\b.*\b(?:phone|bacha|free|left)\b|\b(?:memory|jagah)\s+(?:kitni|kitna)\b", c) \
            and not re.search(r"\b(?:settings?|kholo|clean|saaf)\b", c):
        return Intent("device_info", {"what": "storage"}, orig)
    if re.search(r"\bbattery\b", c) and re.search(r"\b(?:health|temperature|temp|garam|heat|kitni garam)\b", c):
        return Intent("device_info", {"what": "battery"}, orig)
    if re.match(r"^(?:phone|mobile|device)\s+(?:ki|ka)\s+(?:details|info|jankari|jaankari|specs)|^(?:device|phone) info$|^about (?:my )?phone$"
                r"|^android version", c):
        return Intent("device_info", {"what": "all"}, orig)
    if re.match(r"^(?:kaunse|kaun se|kis)\s+(?:wifi|network)\s+se\s+(?:connected|connect) hai|^(?:wifi|network)\s+ka\s+naam|^which (?:wifi|network)", c):
        return Intent("device_info", {"what": "network"}, orig)
    return None


def r_device_setting(c: str, orig: str, now: datetime) -> Intent | None:
    on = re.compile(r"\b(?:on|chalu|enable|laga|lagao|start)\b")
    off = re.compile(r"\b(?:off|band|disable|hata|hatao|stop|lock)\b")
    if re.search(r"\b(?:auto\s*rotat\w*|rotation|screen rotat\w*|rotate)\b", c):
        if off.search(c):
            return Intent("device_setting", {"name": "auto_rotate", "value": False}, orig)
        if on.search(c):
            return Intent("device_setting", {"name": "auto_rotate", "value": True}, orig)
    if re.search(r"\b(?:screen\s*timeout|screen time\s*out|display timeout|sleep time)\b", c):
        secs = parse_duration(c)
        if secs is None:
            return Intent("clarify", {"question": "Kitna screen timeout rakhun?"}, orig)
        return Intent("device_setting", {"name": "screen_timeout", "value": max(15, min(1800, secs))}, orig)
    if re.search(r"\b(?:haptic\w*|touch vibration|vibration feedback)\b", c):
        return Intent("device_setting", {"name": "haptics", "value": not off.search(c)}, orig)
    return None


# ------------------------------------------------------------------ notifications
def r_notif_v2(c: str, orig: str, now: datetime) -> Intent | None:
    o = strip_wake(orig)
    m = re.match(r"^(?P<who>.+?)\s+ko\s+reply\s+(?:karo|kar do|kr do|bhejo|bhej do|do|de do)\s*(?:ki|:|,|-)?\s*(?P<body>.+)$", o, flags=re.I) \
        or re.match(r"^reply\s+to\s+(?P<who>.+?)\s*(?:saying|that|:|,|-)\s*(?P<body>.+)$", o, flags=re.I) \
        or re.match(r"^(?:reply|jawab)\s+(?:do|karo|kar do|bhejo|bhej do|de do|de)\s*(?:ki|that|:|,|-)?\s*(?P<body>.+)$", o, flags=re.I) \
        or re.match(r"^reply\s*(?:with|saying|that|:|-)\s*(?P<body>.+)$", o, flags=re.I)
    if m and re.search(r"\b(?:reply|jawab)\b", c):
        who = (m.groupdict().get("who") or "").strip(" \"'")
        who = re.sub(r"^(?:mere|meri|mera|my)\s+", "", who, flags=re.I)
        body = m.group("body").strip().strip("\"'“”").strip()
        if body:
            return Intent("notif_reply", {"who": who or None, "text": body}, orig)
    if re.search(r"\b(?:summary|summari[sz]e|saransh|short mein batao)\b", c) and \
            re.search(r"\b(?:notifications?|messages?|msgs?|chats?|mails?|emails?|whatsapp)\b", c) or \
            re.match(r"^(?:kya kya (?:aaya|miss kiya|hua)|maine kya miss kiya|what did i miss)\??$", c):
        am = re.search(r"\b(?P<app>whatsapp|instagram|telegram|gmail|sms|messages|mails?|emails?)\b\s*(?:ke|ki|ka)?\s*(?:messages?|notifications?|mails?)?", c)
        app = am.group("app") if am and am.group("app") not in ("messages",) else None
        if app in ("mail", "mails", "email", "emails"):
            app = "gmail"
        return Intent("notif_summary", {"app": app}, orig)
    if re.search(r"\bnotifications?\b", c) and re.search(r"\b(?:clear|saaf|hata do|hatao|dismiss|delete|mita do)\b", c):
        am = re.match(r"^(?:(?:saari|sari|sab|all)\s+)?(?P<app>[a-z0-9 ]+?)\s+(?:ki|ke|ka|wali|wale)\s+(?:saari\s+|sari\s+|sab\s+)?notifications?", c) \
            or re.search(r"\bnotifications?\s+(?:from|of)\s+(?P<app>[a-z0-9 ]+?)(?:\s+(?:clear|dismiss))?$", c)
        app = am.group("app").strip() if am else None
        if app in ("saari", "sari", "sab", "all", "meri", "mere", "phone", "sabhi"):
            app = None
        return Intent("notif_clear", {"app": app}, orig)
    m = re.match(r"^(?P<who>.+?)\s+(?:wali|wala|ki|ka|se aayi)\s+(?:notification|message)\s+(?:kholo|khol do|open karo|open)$", c) \
        or re.match(r"^open (?:the )?(?:notification|message) from (?P<who>.+)$", c)
    if m:
        who = m.group("who").strip()
        if who.split()[-1] in ("latest", "last", "nayi"):
            return None
        return Intent("notif_open", {"who": who}, orig)
    return None


# ------------------------------------------------------------------ screen
def r_screen(c: str, orig: str, now: datetime) -> Intent | None:
    if re.match(r"^(?:(?:ye|yeh|isko|iska|is page ka|is screen ka|screen ka|ye page|this|this page|the screen|screen)\s+)?"
                r"(?:summary|summari[sz]e|saransh|short mein batao)(?:\s+(?:do|dena|karo|kar do|batao|this|it))?$", c) \
            or re.match(r"^(?:summari[sz]e|give me a summary of)\s+(?:this|the screen|this page|it)$", c):
        return Intent("screen_read", {"mode": "summary"}, orig)
    if re.match(r"^(?:screen|display)\s+(?:pe|par|me|mein)\s+(?:kya|kya kya)\s+(?:hai|likha hai|dikh raha hai|chal raha hai)\??$"
                r"|^what'?s on (?:my |the )?screen\??$|^(?:ye|yeh) kya hai screen pe\??$", c):
        return Intent("screen_read", {"mode": "summary"}, orig)
    if re.match(r"^(?:ye|yeh|isko|isse|is|screen|ye page|article|message|screen ka text)\s*(?:ko\s+)?(?:padh|padho|padhke|padh ke|padh kar|read)"
                r"(?:\s+(?:ke|kar))?(?:\s+(?:sunao|suna do|batao|do))?$|^read (?:this|the screen|it|it out|this out|this page)(?: to me| aloud| out)?$"
                r"|^screen padh(?:o|ke sunao| ke sunao)?$", c):
        return Intent("screen_read", {"mode": "read"}, orig)
    return None


# ------------------------------------------------------------------ skills (teach mode)
def r_skills(c: str, orig: str, now: datetime) -> Intent | None:
    m = re.match(r"^(?:sikho|seekho|sikh lo|seekh lo|learn|teach|sikhata hoon|sikhati hoon|sikhaata hoon|main sikhata hoon)"
                 r"(?:\s+(?:ki|that|how to|to))?\s*[:,\-]?\s+(?P<name>.+)$", c) \
        or re.match(r"^(?P<name>.+?)\s+(?:karna\s+)?(?:sikho|seekho|sikh lo|seekh lo)$", c) \
        or re.match(r"^(?:learn|record|teach)\s+(?:a\s+)?(?:new\s+)?(?:skill|task)\s*[:,\-]?\s*(?P<name>.+)$", c) \
        or re.match(r"^(?:teach mode|teaching mode|sikhane ka mode)(?:\s+(?:on|chalu|start))?(?:\s*[:,\-]\s*(?P<name>.+))?$", c)
    if m:
        name = (m.groupdict().get("name") or "").strip(" :,-")
        name = re.sub(r"^(?:skill|task)\s+", "", name)
        return Intent("skill_teach", {"name": name}, orig)
    if re.match(r"^(?:(?:ho gaya|ho gya|done|bas|theek hai)\s+)?(?:(?:recording|skill|ye|yeh)\s+)?"
                r"(?:save|save karo|save kar do|save kr do|save it|save kar lo|save karlo)$", c) \
            or re.match(r"^(?:recording|teaching|teach mode)\s+(?:band|stop|khatam|finish|done)(?:\s+(?:karo|kar do))?$", c):
        return Intent("skill_save", {}, orig)
    if re.match(r"^(?:recording|skill|teaching|teach mode)\s+(?:cancel|rehne do|hata do|discard)(?:\s+karo)?$|^cancel (?:the )?(?:recording|teaching)$", c):
        return Intent("skill_cancel", {}, orig)
    if re.match(r"^(?:meri |my |saari |sab )?skills(?:\s+(?:dikhao|batao|list|kya hai|kaun si hai))?\??$"
                r"|^(?:kya kya sikha|tumne kya kya seekha|what have you learned|list skills)\??$", c):
        return Intent("skill_list", {}, orig)
    m = re.match(r"^(?P<name>.+?)\s+skill\s+(?:delete|hata do|hatao|mita do|remove|bhool jao)(?:\s+(?:karo|kar do))?$", c) \
        or re.match(r"^(?:delete|remove|forget)\s+(?:the\s+)?skill\s+(?P<name>.+)$", c)
    if m:
        return Intent("skill_delete", {"name": m.group("name").strip()}, orig)
    m = re.match(r"^(?P<name>.+?)\s+skill\s+(?:chalao|chala do|run karo|run|karo)$", c) or re.match(r"^run (?:the )?skill\s+(?P<name>.+)$", c)
    if m:
        return Intent("skill_run", {"name": m.group("name").strip()}, orig)
    return None


# ------------------------------------------------------------------ routine management
def r_routine_mgmt(c: str, orig: str, now: datetime) -> Intent | None:
    if re.match(r"^(?:meri |mere |my |saari |sab |sabhi )?(?:routines?|scenes?|automations?)(?:\s+(?:dikhao|batao|list|kya hai|kaun si hai))?\??$"
                r"|^(?:list|show)\s+(?:my\s+)?(?:routines|automations)$", c):
        return Intent("routine_list", {}, orig)
    if re.match(r"^(?:meri |mere |my |saare |sab )?reminders?(?:\s+(?:dikhao|batao|list|kya hai|kitne hai))?\??$|^(?:list|show)\s+(?:my\s+)?reminders$", c):
        return Intent("routine_list", {"only": "reminders"}, orig)
    m = re.match(r"^(?P<name>.+?)\s+(?:routine|scene|automation)\s+(?:chalao|chala do|run karo|run|start karo|shuru karo)$", c) \
        or re.match(r"^(?:run|start)\s+(?:the\s+)?(?P<name>.+?)\s+(?:routine|scene)$", c)
    if m:
        return Intent("routine_run", {"name": m.group("name").strip()}, orig)
    m = re.match(r"^(?P<name>.+?)\s+(?:routine|scene|automation|reminder)\s+(?:delete|hata do|hatao|mita do|remove)(?:\s+(?:karo|kar do))?$", c) \
        or re.match(r"^(?:delete|remove)\s+(?:the\s+)?(?P<name>.+?)\s+(?:routine|reminder|automation)$", c)
    if m:
        return Intent("routine_delete", {"name": m.group("name").strip()}, orig)
    m = re.match(r"^(?P<name>.+?)\s+(?:routine|automation)\s+(?P<v>on|off|band|chalu|enable|disable|pause|resume)(?:\s+(?:karo|kar do))?$", c) \
        or re.match(r"^(?P<v>enable|disable|pause|resume)\s+(?:the\s+)?(?P<name>.+?)\s+(?:routine|automation)$", c)
    if m:
        return Intent("routine_toggle", {"name": m.group("name").strip(), "on": m.group("v") in ("on", "chalu", "enable", "resume")}, orig)
    return None


# ------------------------------------------------------------------ bridge / inbox
def r_bridge(c: str, orig: str, now: datetime) -> Intent | None:
    if re.match(r"^(?:inbox|phone inbox|nixin inbox)(?:\s+(?:dikhao|batao|check karo))?$|^phone se kya (?:aaya|bheja)\??$"
                r"|^(?:what did i share|shared items)$", c):
        return Intent("inbox", {"action": "list"}, orig)
    if re.match(r"^(?:inbox|inbox folder|nixin inbox)\s+(?:kholo|khol do|open karo|open)$|^open (?:the )?inbox(?: folder)?$", c):
        return Intent("inbox", {"action": "open"}, orig)
    if re.search(r"\bwallpaper\b", c) and re.search(r"\b(?:ye|yeh|is|isko|last|wo|woh|that|this|shared|bheji)\b", c) \
            and re.search(r"\b(?:photo|image|pic|picture|tasveer|wallpaper)\b", c) and re.search(r"\b(?:laga|lagao|laga do|set|bana|bana do|rakh|rakho)\b", c):
        target = "lock" if re.search(r"\block\s*screen\b", c) else ("home" if re.search(r"\bhome\s*screen\b", c) else "both")
        return Intent("inbox", {"action": "wallpaper", "target": target}, orig)
    if re.match(r"^(?:last|inbox ki|wo|woh|that)\s+file\s+(?:phone|mobile)\s+(?:pe|par)\s+(?:bhejo|bhej do|send karo)$|^send (?:the )?last file to (?:my )?phone$", c):
        return Intent("inbox", {"action": "push_last"}, orig)
    return None


RULES_V2_EARLY = [r_skills, r_routine, r_reminder, r_notif_v2]
RULES_V2_MID = [r_call_control, r_find_phone]
RULES_V2_LATE = [r_pc, r_bridge, r_routine_mgmt]
RULES_V2_INFO = [r_weather, r_briefing, r_screen]
RULES_V2_DEVICE = [r_now_playing, r_usage, r_device_info, r_device_setting]

__all__ = ["ClockTime", "RULES_V2_DEVICE", "RULES_V2_EARLY", "RULES_V2_INFO", "RULES_V2_LATE", "RULES_V2_MID"]
