"""Deterministic Hinglish/English command router (no LLM, ~1 ms).

``route(text)`` returns a list of Intents or ``None`` when the command needs the LLM.
Message bodies are always extracted from the ORIGINAL text so nothing the user said
is rewritten. Anything unclear is left to the classifier instead of guessing.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from nixin.router.normalize import clean, has_devanagari, strip_wake
from nixin.router.timeparse import parse_clock, parse_duration


@dataclass
class Intent:
    kind: str
    params: dict = field(default_factory=dict)
    source_text: str = ""

    @property
    def external(self) -> bool:
        return self.kind in ("message", "call")


@dataclass
class RouteResult:
    intents: list[Intent] | None
    cleaned: str

    @property
    def resolved(self) -> bool:
        return bool(self.intents)


# ------------------------------------------------------------------ vocabulary
_DO = r"(?:karo|kar|kar do|kardo|kar de|karde|kariye|kijiye|karna|krdo|kr do|kro|kr)"
_ON = r"(?:on|chalu|chaalu|jala|jalao|jala do|jalado|start|enable|kholo|khol do|laga|lagao|activate)"
_OFF = r"(?:off|band|bandh|bujha|bujhao|bujha do|bujhado|stop|disable|hata|hatao|hata do|deactivate|close)"
_UP = r"(?:badha|badhao|badha do|badhado|badhaa|bada|bdha|bdhao|up|increase|zyada|jyada|tez|high|louder|raise|upar|loud|full)"
_DOWN = r"(?:kam|ghata|ghatao|ghata do|down|decrease|low|dheere|dhire|dheema|dhima|lower|neeche|niche|halka|quieter|reduce)"
_POSSESSIVE = r"^(?:mere|meri|mera|my|apne|apni|apna|to|the)\s+"

_SAY_VERBS = (
    r"(?:bol(?:o|na)?(?: do| de| dena)?|keh(?:o|na)?(?: do| de| dena)?|kaho|bata(?:o|na)?(?: do| de| dena)?"
    r"|likh(?:o|na)?(?: do| de| dena)?|message\s+(?:kar(?:o|na)?|bhej(?:o|na)?|send kar(?:o)?)(?: do| de| dena)?"
    r"|msg\s+(?:kar(?:o)?|bhej(?:o)?)(?: do| de)?|text\s+kar(?:o)?(?: do| de)?|sms\s+(?:kar(?:o)?|bhej(?:o)?)(?: do| de)?"
    r"|(?:whats\s*app|whatsap|watsapp)\s+kar(?:o|na)?(?: do| de| dena)?|bhej(?:o|na)?(?: do| de| dena)?"
    r"|send\s+kar(?:o)?(?: do| de)?)"
)
_CHAN = r"(?:whats\s*app|whatsap|watsapp|wa|sms|message|msg|text)"

_APP_BLACKLIST = {"", "karo", "kar", "do", "it", "this", "that", "app", "ye", "yeh", "wo", "woh", "isko", "usko"}
_CALL_BLACKLIST = {"history", "log", "logs", "recording", "records", "list", "karo", "kar", "lagao", "back", "me"}


def _chan(raw: str | None) -> str:
    if not raw:
        return "default"
    r = raw.lower().replace(" ", "")
    if r.startswith(("whats", "wa", "watsapp")):
        return "whatsapp"
    if r in ("sms", "text"):
        return "sms"
    return "default"


def _who(raw: str) -> str:
    w = re.sub(_POSSESSIVE, "", raw.strip(), flags=re.I)
    w = re.sub(r"\s+(?:ko|ke|ki|ka)$", "", w, flags=re.I)
    return w.strip(" \"'.,:-")


def _body(raw: str) -> str:
    b = raw.strip()
    b = re.sub(r"^(?:ki|ke|k|that|saying|to say)\s+", "", b, flags=re.I)
    b = b.strip().strip("\"'“”‘’").strip()
    return b


# ------------------------------------------------------------------ rules
Rule = Callable[[str, str, datetime], Intent | None]


def _r_message(c: str, orig: str, now: datetime) -> Intent | None:
    o = orig.strip()
    pats = [
        # WhatsApp pe Rahul ko bol main 10 min late hoon / Rahul ko WhatsApp pe bolo ki ...
        rf"^(?:(?P<ch1>{_CHAN})\s+(?:pe|par|pr|se|on)\s+)?(?P<who>.+?)\s+ko\s+(?:(?P<ch2>{_CHAN})\s+(?:pe|par|pr|se)\s+)?"
        rf"(?:(?P<ch3>{_CHAN})\s+)?(?P<verb>{_SAY_VERBS})(?:\s+(?:ki|ke|k|that))?\s*[:,\-]?\s+(?P<body>.+)$",
        # send a whatsapp to Rahul saying I'm late / send message to mom: on my way
        rf"^(?:send|write|drop)\s+(?:a\s+|an\s+)?(?P<ch1>{_CHAN})(?:\s+message)?\s+to\s+(?P<who>.+?)"
        rf"(?:\s+(?:on|via)\s+(?P<ch2>{_CHAN}))?\s*(?:\s+saying|\s+that|:|,|-)\s*(?P<body>.+)$",
        # tell Rahul on whatsapp that I'm late / whatsapp Rahul: I'm late / text mom I'll be late
        rf"^(?P<verb>tell|message|text|whatsapp|msg|sms)\s+(?P<who>[^:,]+?)(?:\s+(?:on|via)\s+(?P<ch2>{_CHAN}))?"
        rf"\s*(?:\s+saying|\s+that|\s+to say|:|,|-)\s*(?P<body>.+)$",
        # send "hi" to Rahul on whatsapp
        rf"^send\s+(?P<body>.+?)\s+to\s+(?P<who>[\w .]+?)\s+(?:on|via)\s+(?P<ch2>{_CHAN})$",
    ]
    for i, p in enumerate(pats):
        m = re.match(p, o, flags=re.I)
        if not m:
            continue
        g = m.groupdict()
        who, body = _who(g.get("who") or ""), _body(g.get("body") or "")
        if not who or not body or len(who.split()) > 4:
            continue
        verb = (g.get("verb") or "").lower()
        ch = g.get("ch1") or g.get("ch2") or g.get("ch3")
        if not ch and verb:
            if verb.startswith(("whats", "watsapp")):
                ch = "whatsapp"
            elif verb.startswith(("sms", "text")):
                ch = "sms"
        if i == 2 and verb == "tell" and not ch:
            ch = None
        return Intent("message", {"channel": _chan(ch), "who": who, "body": body}, orig)
    return None


def _r_call(c: str, orig: str, now: datetime) -> Intent | None:
    pats = [
        rf"^(?P<who>.+?)\s+ko\s+(?:call|phone|dial|ring)\s*(?:{_DO}|lagao|laga|laga do|lagado|milao|mila|mila do|kariye)?$",
        r"^(?:call|phone|dial)\s+(?:karo|lagao|laga|kar)\s+(?P<who>.+)$",
        r"^(?:call|dial|ring)\s+(?P<who>.+?)(?:\s+(?:on|pe)\s+(?:phone|mobile))?$",
    ]
    for p in pats:
        m = re.match(p, c)
        if m:
            who = _who(m.group("who"))
            if who and who not in _CALL_BLACKLIST and not who.startswith(("history", "log")) and len(who.split()) <= 4:
                if re.match(r"^(?:whatsapp|video)\b", who):
                    return None  # whatsapp/video calls -> agent
                return Intent("call", {"who": who}, orig)
    return None


def _r_alarm(c: str, orig: str, now: datetime) -> Intent | None:
    remind = re.search(r"\b(?:yaad dila(?:na|o|na)?|yad dila(?:na|o)?|remind me|reminder)\b", c)
    if not (re.search(r"\b(?:alarm|uthana|utha dena|utha do|jagana|jaga dena|jaga do|wake me)\b", c) or remind):
        return None
    if re.search(r"\b(?:volume|awaa?z|sound|ringtone)\b", c):
        return None
    if re.search(r"\b(?:band|off|cancel|hata|delete|remove)\b", c) and not remind:
        return Intent("agent", {"goal": "Turn off / delete the requested alarm in the Clock app", "hint": "open_app clock"}, orig)
    ct = parse_clock(c, now)
    if ct is None:
        return Intent("clarify", {"question": "Kitne baje ka alarm lagaun?"}, orig)
    label = None
    if remind:
        m = re.search(r"\b(?:ki|that|to|ke liye)\s+(.+)$", strip_wake(orig), flags=re.I)
        label = m.group(1).strip()[:80] if m else "Reminder"
    return Intent("alarm", {"hour": ct.hour, "minute": ct.minute, "day_hint": ct.day_hint, "label": label}, orig)


def _r_timer(c: str, orig: str, now: datetime) -> Intent | None:
    if not re.search(r"\b(?:timer|countdown|stopwatch)\b", c):
        return None
    secs = parse_duration(c)
    if secs is None:
        return Intent("clarify", {"question": "Kitni der ka timer lagaun?"}, orig)
    return Intent("timer", {"seconds": secs}, orig)


def _r_search(c: str, orig: str, now: datetime) -> Intent | None:
    play_v = r"(?:chalao|chala|chala do|chalado|laga|lagao|laga do|play karo|play kar|play|bajao|baja|baja do|sunao|suna)"
    find_v = r"(?:search karo|search kar|search|dhundo|dhoondo|dhundho|dhund|khojo|dikhao|dikha|kholo)"
    for engine, names in (("youtube", r"youtube"), ("spotify", r"spotify"), ("playstore", r"play ?store"), ("maps", r"(?:google )?maps?")):
        m = re.match(rf"^{names}\s+(?:pe|par|pr|on|mein|me)\s+(?P<q>.+?)(?:\s+(?P<v>{play_v}|{find_v}))?$", c)
        if not m:
            m = re.match(rf"^(?P<v>play|search|search for|find|look up|open)\s+(?P<q>.+?)\s+(?:on|in)\s+{names}$", c)
        if m:
            q = m.group("q").strip()
            v = (m.group("v") or "").strip()
            if q:
                play = engine in ("youtube", "spotify") and bool(re.match(play_v, v) or v == "play")
                return Intent("search", {"engine": engine, "query": q, "play": play}, orig)
    m = re.match(rf"^(?P<q>.+?)\s+(?:ke|ka|ki)\s+(?:gaane|gane|gana|gaana|songs?)\s+{play_v}$", c)
    if m:
        return Intent("search", {"engine": "youtube", "query": m.group("q") + " songs", "play": True}, orig)
    m = re.match(
        r"^(?:google\s+(?:pe|par|pr|on)\s+)?(?P<q>.+?)\s+(?:google karo|google kar|search karo|search kar|dhundo|dhoondo|khojo)$", c
    ) or re.match(r"^(?:google\s+(?:pe|par|pr|on|karo|kar)|search(?:\s+for)?|look up|google)\s+(?P<q>.+)$", c)
    if m and m.group("q") and not re.match(r"^(?:google|search)$", m.group("q")) and not re.search(
        r"\b(?:kholo|khol|khol do|open|open karo|launch)$", m.group("q")
    ):
        return Intent("search", {"engine": "web", "query": m.group("q").strip(), "play": False}, orig)
    m = re.match(r"^(?:navigate to|directions to|take me to|rasta dikhao|le chalo)\s+(?P<q>.+)$", c) or re.match(
        r"^(?P<q>.+?)\s+(?:ka rasta dikhao|ka rasta batao|ka rasta|tak le chalo|le chalo|ke liye navigation|navigate karo|ka route|ka route dikhao|tak ka rasta)$", c
    )
    if m:
        return Intent("navigate", {"destination": m.group("q").strip()}, orig)
    return None


def _r_volume(c: str, orig: str, now: datetime) -> Intent | None:
    has_vol = re.search(r"\b(?:volume|awaa?z|aawaa?z|sound)\b", c)
    bare = re.match(r"^(?:mute|unmute|louder|quieter)(?:\s+" + _DO + r")?$", c)
    if not (has_vol or bare):
        return None
    if re.search(r"\b(?:setting|settings)\b", c):
        return None
    stream = "media"
    if re.search(r"\b(?:ring|ringing|ringtone|ringer)\b", c):
        stream = "ring"
    elif re.search(r"\balarm\b", c):
        stream = "alarm"
    elif re.search(r"\b(?:call|calling|in-call)\b", c):
        stream = "call"
    elif re.search(r"\bnotification\b", c):
        stream = "notification"
    p: dict = {"stream": stream}
    m = re.search(r"\b(\d{1,3})\s*(?:%|percent|pratishat)?", c)
    if re.search(r"\bunmute\b", c):
        p["action"] = "unmute"
    elif re.search(r"\b(?:mute|zero)\b", c) or re.search(r"\bvolume\s+(?:band|0)\b", c):
        p["action"] = "mute"
    elif re.search(r"\b(?:full|max|maximum|pura|poora|sabse zyada|highest|sabse tez)\b", c):
        p["action"] = "max"
    elif m and int(m.group(1)) <= 100 and not re.search(r"\b(?:step|steps|baar|level|levels)\b", c):
        p["action"], p["percent"] = "set", int(m.group(1))
    elif re.search(rf"\b{_UP}\b", c):
        p["action"] = "up"
    elif re.search(rf"\b{_DOWN}\b", c):
        p["action"] = "down"
    else:
        return None
    if p["action"] in ("up", "down"):
        steps = 2
        ms = re.search(r"\b(\d{1,2})\s*(?:step|steps|baar|level|levels)\b", c)
        if ms:
            steps = max(1, min(15, int(ms.group(1))))
        elif re.search(r"\b(?:thoda|thodi|little|bit|slightly|halka sa)\b", c):
            steps = 1
        elif re.search(r"\b(?:bahut|bohot|bahot|a lot|much|zyada|jyada)\b", c):
            steps = 4
        p["steps"] = steps
    return Intent("phone", {"method": "device.volume", "params": p}, orig)


def _r_torch(c: str, orig: str, now: datetime) -> Intent | None:
    if not re.search(r"\b(?:torch|flash)\b", c):
        return None
    on = not re.search(rf"\b{_OFF}\b", c)
    return Intent("phone", {"method": "device.torch", "params": {"on": on}}, orig)


def _r_brightness(c: str, orig: str, now: datetime) -> Intent | None:
    if not re.search(r"\b(?:brightness|roshni|screen light|screen ki light)\b", c):
        return None
    m = re.search(r"\b(\d{1,3})\s*(?:%|percent)?", c)
    if re.search(r"\b(?:auto|automatic|adaptive)\b", c):
        p = {"action": "auto"}
    elif re.search(r"\b(?:full|max|maximum|pura|poora)\b", c):
        p = {"action": "set", "percent": 100}
    elif m and int(m.group(1)) <= 100:
        p = {"action": "set", "percent": int(m.group(1))}
    elif re.search(rf"\b{_UP}\b", c):
        p = {"action": "up"}
    elif re.search(rf"\b{_DOWN}\b", c):
        p = {"action": "down"}
    else:
        return None
    return Intent("phone", {"method": "device.brightness", "params": p}, orig)


def _r_ringer_dnd(c: str, orig: str, now: datetime) -> Intent | None:
    if re.search(r"\b(?:dnd|do not disturb|disturb mat)\b", c):
        on = not re.search(rf"\b{_OFF}\b", c)
        return Intent("phone", {"method": "device.dnd", "params": {"on": on}}, orig)
    if re.search(r"\bsilent\b", c):
        if re.search(rf"\b(?:{_OFF}|hata|hatao|normal)\b", c) and not re.search(r"\b(?:silent (?:kar|karo|kar do|mode (?:on|pe|par)))", c):
            return Intent("phone", {"method": "device.ringer", "params": {"mode": "normal"}}, orig)
        return Intent("phone", {"method": "device.ringer", "params": {"mode": "silent"}}, orig)
    if re.search(r"\bvibrat(?:e|ion|or)\b", c):
        mode = "normal" if re.search(rf"\b{_OFF}\b", c) else "vibrate"
        return Intent("phone", {"method": "device.ringer", "params": {"mode": mode}}, orig)
    if re.search(r"\b(?:ringer|general mode|normal mode|ring mode)\b", c) and not re.search(r"\bvolume\b", c):
        return Intent("phone", {"method": "device.ringer", "params": {"mode": "normal"}}, orig)
    return None


_TOGGLES = [
    ("wifi", r"wifi"),
    ("bluetooth", r"bluetooth"),
    ("mobile_data", r"(?:mobile data|data|internet)"),
    ("hotspot", r"(?:hotspot|hot spot)"),
    ("location", r"(?:location|gps)"),
    ("airplane", r"(?:airplane|aeroplane|flight)(?: mode)?"),
    ("nfc", r"nfc"),
]


def _r_toggle(c: str, orig: str, now: datetime) -> Intent | None:
    for setting, pat in _TOGGLES:
        if re.search(rf"\b{pat}\b", c):
            if re.search(r"\bsettings?\b", c) and not re.search(rf"\b(?:{_ON}|{_OFF})\b", c.replace("kholo", "")):
                panel = {"mobile_data": "mobile_data", "airplane": "airplane"}.get(setting, setting)
                return Intent("phone", {"method": "device.settings", "params": {"panel": panel}}, orig)
            if re.search(rf"\b{_OFF}\b", c):
                return Intent("toggle", {"setting": setting, "on": False}, orig)
            if re.search(rf"\b{_ON}\b", c):
                return Intent("toggle", {"setting": setting, "on": True}, orig)
            if setting == "mobile_data":
                return None  # "data" is too generic without on/off
    return None


_GLOBAL = [
    ("back", r"^(?:go back|back|peeche|piche|wapas|wapis|vapas|back jao|peeche jao|piche jao|ek step peeche)(?: jao| chalo| karo| ja)?$"),
    ("home", r"^(?:go home|home|home screen|main screen|home page)(?: pe| par)?(?: jao| chalo| karo| ja| le chalo)?$"),
    ("recents", r"^(?:recent apps?|recents|recent|open apps|khule apps)(?: dikhao| kholo| khol| open karo)?$"),
    ("notifications", r"^(?:notification (?:panel|shade|bar|center)|pull down notification|open notification|notification kholo|notification khol|notification dikhao)(?: kholo| khol| open karo| dikhao)?$"),
    ("quick_settings", r"^(?:quick settings?|control (?:center|panel))(?: kholo| khol| open karo| dikhao)?$"),
    ("lock_screen", r"^(?:(?:phone|screen|mobile|device) (?:lock|lok)(?: " + _DO + r")?|lock (?:the )?(?:phone|screen|mobile)|lock " + _DO + r")$"),
    ("screenshot", r"^(?:screenshot|take (?:a )?screenshot)(?: le| lo| lelo| le lo| lena| " + _DO + r"| khicho| kheecho)?$"),
    ("power_dialog", r"^(?:power (?:menu|button|options|dialog))(?: kholo| khol| dikhao)?$"),
    ("split_screen", r"^split screen(?: " + _DO + r")?$"),
]


def _r_global(c: str, orig: str, now: datetime) -> Intent | None:
    for action, pat in _GLOBAL:
        if re.match(pat, c):
            return Intent("phone", {"method": "device.global", "params": {"action": action}}, orig)
    m = re.match(r"^(?:(?P<which>[a-z ]+?)\s+)?settings?\s*(?:kholo|khol|open|open karo|dikhao|pe jao)?$", c)
    if m and re.search(r"\bsettings?\b", c) and (m.group("which") is None or m.group("which") in (
        "phone", "mobile", "sound", "display", "battery", "apps", "app", "accessibility", "location", "bluetooth", "wifi", "notification")):
        which = (m.group("which") or "main").strip()
        panel = {"phone": "main", "mobile": "main", "app": "apps", "notification": "notification_access"}.get(which, which)
        return Intent("phone", {"method": "device.settings", "params": {"panel": panel}}, orig)
    return None


def _r_media(c: str, orig: str, now: datetime) -> Intent | None:
    thing = r"(?:gana|gaana|gaane|gane|song|songs|music|video|track|podcast)"
    if re.match(rf"^(?:next|agla|agle|skip)(?:\s+{thing})?(?:\s+(?:chalao|chala|lagao|play karo|{_DO}))?$", c) or re.match(rf"^{thing}\s+(?:next|skip|badlo|change)(?:\s+{_DO})?$", c):
        return Intent("phone", {"method": "media.control", "params": {"action": "next"}}, orig)
    if re.match(rf"^(?:previous|prev|pichla|pichle|pehle wala|peeche wala)(?:\s+{thing})?(?:\s+(?:chalao|chala|lagao|play karo|{_DO}))?$", c):
        return Intent("phone", {"method": "media.control", "params": {"action": "previous"}}, orig)
    if re.match(rf"^(?:pause|resume|play)(?:\s+(?:the\s+)?{thing})?(?:\s+{_DO})?$", c):
        action = "pause" if c.startswith("pause") else "play"
        return Intent("phone", {"method": "media.control", "params": {"action": action}}, orig)
    m = re.match(rf"^{thing}\s+(?P<v>chalao|chala|chala do|chalu karo|play karo|bajao|resume karo|shuru karo|pause karo|pause|band karo|band kar do|band|roko|rok do|ruk|ruko|stop karo|stop)$", c)
    if m:
        v = m.group("v")
        action = "pause" if re.match(r"(?:pause|band|rok|ruk|stop)", v) else "play"
        return Intent("phone", {"method": "media.control", "params": {"action": action}}, orig)
    return None


def _r_notifications(c: str, orig: str, now: datetime) -> Intent | None:
    if not re.search(r"\bnotification\b", c):
        return None
    if not re.search(r"\b(?:padh|padho|padhke|padh ke|parh|parho|read|bata|batao|sunao|suna|dikhao|dikha|check|kya aaya|kya ayi|kya aayi|aaya|aayi|latest|new|nayi|naye|kya hai|kaun si|any)\b", c):
        return None
    app = None
    m = re.search(r"\b(?P<app>[a-z0-9]+(?: [a-z0-9]+)?)\s+(?:ki|ka|ke|se aayi|se aaya|wali|wale)\s+(?:latest\s+|last\s+|nayi\s+|new\s+)?notification", c) or re.search(
        r"\bnotification(?:s)?\s+(?:from|of)\s+(?P<app>[a-z0-9]+(?: [a-z0-9]+)?)", c)
    if m and m.group("app") not in ("meri", "mere", "my", "sabhi", "sab", "all", "latest", "last", "new", "nayi", "phone"):
        app = m.group("app")
    limit = 1 if re.search(r"\b(?:latest|last|aakhri|akhri|recent)\b", c) else 5
    return Intent("notifications", {"app": app, "limit": limit}, orig)


def _r_status(c: str, orig: str, now: datetime) -> Intent | None:
    if re.search(r"\bbattery\b", c) and not re.search(r"\b(?:saver|setting|settings|optimi[sz]ation)\b", c):
        return Intent("status", {"what": "battery"}, orig)
    if re.match(r"^(?:phone|mobile) (?:ka |ki )?(?:status|haal|halat)(?: kya hai| batao| bata)?$", c):
        return Intent("status", {"what": "all"}, orig)
    if re.match(r"^(?:abhi )?(?:time|samay|kitne baje|what time|what's the time|whats the time|kya time)(?: kya| hua| hai| ho gaya| is it| batao| bata)*\??$", c):
        return Intent("clock", {"what": "time"}, orig)
    if re.match(r"^(?:aaj )?(?:ki )?(?:date|tarikh|tareekh|what's the date|whats the date|kya date|aaj kya din|today's date|what day)(?: hai| kya hai| batao| bata| is it| is today)*\??$", c):
        return Intent("clock", {"what": "date"}, orig)
    return None


def _r_remember(c: str, orig: str, now: datetime) -> Intent | None:
    m = re.match(r"^(?:yaad rakh(?:na|o|iye)?|yad rakh(?:na|o)?|remember|note kar(?:o|lo|le)?)(?:\s+(?:ki|that|ye|yeh))?[\s:,]+(?P<fact>.+)$", strip_wake(orig), flags=re.I)
    if m and len(m.group("fact").strip()) > 3:
        return Intent("remember", {"fact": m.group("fact").strip()}, orig)
    return None


_CHAT = [
    (r"^(?:hi|hello|hey|namaste|namaskar|hola|yo|hii+|helo)$", "greet"),
    (r"^(?:thanks|thank you|thank u|thanku|shukriya|dhanyavad|dhanyawad|thx|ty)(?: nixin| yaar| bhai)?$", "thanks"),
    (r"^(?:kaise ho|kaisi ho|how are you|kya haal hai|how r u)\??$", "howareyou"),
    (r"^(?:who are you|kaun ho|tum kaun ho|what can you do|kya kya kar sakte ho|kya kar sakti ho|help)\??$", "intro"),
]


def _r_chat(c: str, orig: str, now: datetime) -> Intent | None:
    for pat, kind in _CHAT:
        if re.match(pat, c):
            return Intent("chat", {"kind": kind}, orig)
    return None


def _r_cancel(c: str, orig: str, now: datetime) -> Intent | None:
    if re.match(r"^(?:stop|ruk|ruko|ruk jao|ruk ja|bas|bas karo|bas kar|cancel|cancel karo|cancel kar|abort|rehne do|rahne do|chhodo|chodo|mat karo|stop it|stop everything|sab band karo)$", c):
        return Intent("cancel", {}, orig)
    return None


def _r_open_app(c: str, orig: str, now: datetime) -> Intent | None:
    m = re.match(r"^(?:open|launch|start|kholo|khol|chalu karo|chalao)\s+(?P<app>.+?)(?:\s+app)?$", c) or re.match(
        r"^(?P<app>.+?)(?:\s+app)?\s+(?:kholo|khol|khol do|khol de|kholna|open karo|open kar|open kar do|open|chalu karo|chalu kar|launch karo|start karo|pe jao|par jao|mein jao)$", c)
    if not m:
        return None
    app = m.group("app").strip()
    if app in _APP_BLACKLIST or len(app.split()) > 4:
        return None
    return Intent("open_app", {"name": app}, orig)


RULES: list[Rule] = [
    _r_cancel, _r_chat, _r_remember, _r_message, _r_alarm, _r_timer, _r_call, _r_search, _r_notifications,
    _r_volume, _r_torch, _r_brightness, _r_ringer_dnd, _r_toggle, _r_media, _r_global, _r_status, _r_open_app,
]
_CONSUMING = {"message", "remember", "search", "navigate", "alarm", "agent"}
_SPLIT = re.compile(r"\s+(?:aur phir|aur fir|and then|uske baad|iske baad|fir|phir|then|and|aur|,)\s+", re.I)


def _route_one(orig: str, now: datetime) -> Intent | None:
    c = clean(orig)
    if not c:
        return None
    for rule in RULES:
        it = rule(c, orig, now)
        if it is not None:
            return it
    return None


def route(text: str, now: datetime | None = None) -> RouteResult:
    now = now or datetime.now()
    orig = strip_wake(text)
    cleaned = clean(text)
    if not cleaned:
        return RouteResult(None, cleaned)

    whole = _route_one(orig, now)
    if whole is not None and (whole.kind in _CONSUMING or not _SPLIT.search(orig)):
        return RouteResult([whole], cleaned)

    # multi-part: "torch on karo aur volume full kar do", "Instagram khol aur latest notification padh"
    parts = [p for p in _SPLIT.split(orig) if p.strip()]
    if len(parts) > 1:
        intents: list[Intent] = []
        for part in parts:
            it = _route_one(part, now)
            if it is None or it.kind in ("clarify", "chat"):
                return RouteResult(None, cleaned)
            # carry app context: "Instagram khol aur latest notification padh"
            if it.kind == "notifications" and not it.params.get("app") and intents and intents[-1].kind == "open_app":
                it.params["app"] = intents[-1].params["name"]
            intents.append(it)
        return RouteResult(intents, cleaned)

    if whole is not None:
        return RouteResult([whole], cleaned)
    return RouteResult(None, cleaned)


def looks_devanagari(text: str) -> bool:
    return has_devanagari(text)
