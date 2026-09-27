"""Hinglish + English clock times and durations.

Examples handled:
  "6 baje", "subah 6:30", "saade 6", "sawa 7", "paune 8", "raat 11 baje", "7 pm",
  "kal subah 6 baje", "half past six", "quarter to seven", "10 minute baad"
  durations: "5 minute", "dedh ghanta", "aadha ghanta", "2 min 30 sec", "90 seconds"
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

_WORD_NUM = {
    "ek": 1, "do": 2, "teen": 3, "tin": 3, "char": 4, "chaar": 4, "panch": 5, "paanch": 5, "chhe": 6, "che": 6,
    "chah": 6, "chhah": 6, "saat": 7, "sat": 7, "aath": 8, "ath": 8, "nau": 9, "no": 9, "das": 10, "dus": 10,
    "gyarah": 11, "gyara": 11, "barah": 12, "bara": 12, "pandrah": 15, "bees": 20, "tees": 30, "chalis": 40,
    "pachas": 50, "pachaas": 50,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
    "forty five": 45, "fifty": 50, "sixty": 60, "a": 1, "an": 1,
}
_NUM = r"(\d{1,2}|" + "|".join(sorted((re.escape(k) for k in _WORD_NUM if k not in ("a", "an", "no", "do")), key=len, reverse=True)) + r")"


def _num(tok: str) -> int | None:
    tok = tok.strip()
    if tok.isdigit():
        return int(tok)
    return _WORD_NUM.get(tok)


@dataclass
class ClockTime:
    hour: int
    minute: int
    explicit_meridiem: bool
    day_hint: str | None  # "today" | "tomorrow" | None
    relative: bool = False

    def next_occurrence(self, now: datetime) -> datetime:
        t = now.replace(hour=self.hour, minute=self.minute, second=0, microsecond=0)
        if t <= now:
            t += timedelta(days=1)
        return t


_MORNING = r"(?:subah|subeh|savere|sawere|morning|sube|early morning|a\.?m\.?|am)"
_NOON = r"(?:dopahar|dophar|dopehar|afternoon|noon)"
_EVENING = r"(?:shaam|sham|evening)"
_NIGHT = r"(?:raat|rat|night|tonight)"
_PM = r"(?:p\.?m\.?|pm)"


_UNIT_AHEAD = r"(?=\s*(?:baje|bje|minute|minat|min|ghant|hour|hr|second|sec))"


def _pre(text: str) -> str:
    t = f" {text.lower()} "
    t = re.sub(r"\bdo\b" + _UNIT_AHEAD, "2", t)
    t = re.sub(r"\bno\b" + _UNIT_AHEAD, "9", t)
    t = re.sub(r"\ban?\b" + r"(?=\s*(?:minute|min|hour|second))", "1", t)
    return t


def parse_clock(text: str, now: datetime | None = None) -> ClockTime | None:
    now = now or datetime.now()
    t = _pre(text)

    day_hint = None
    if re.search(r"\b(?:kal|tomorrow|kal subah|agle din)\b", t):
        day_hint = "tomorrow"
    elif re.search(r"\b(?:aaj|aj|today|tonight)\b", t):
        day_hint = "today"

    # relative: "10 minute baad", "in 10 minutes", "1 ghante baad"
    m = re.search(rf"\b(?:in\s+)?{_NUM}\s*(min|minute|minutes|mins|minat|ghante|ghanta|ghanton|hour|hours|hr|hrs)\b\s*(?:baad|bad|later|mein|me|main)?", t)
    if m and re.search(r"\b(?:baad|bad|later|in)\b", t):
        n = _num(m.group(1)) or 0
        unit = m.group(2)
        delta = timedelta(hours=n) if unit.startswith(("ghant", "hour", "hr")) else timedelta(minutes=n)
        target = now + delta
        return ClockTime(target.hour, target.minute, True, None, relative=True)

    hour: int | None = None
    minute = 0
    # "half past six" / "quarter past six" / "quarter to seven"
    m = re.search(rf"\b(half|quarter) (past|to) {_NUM}\b", t)
    if m:
        base = _num(m.group(3))
        if base is not None:
            if m.group(1) == "half":
                hour, minute = base, 30
            elif m.group(2) == "past":
                hour, minute = base, 15
            else:
                hour, minute = (base - 1) % 12 or 12, 45
    if hour is None:
        # "saade 6" (6:30), "sawa 6" (6:15), "paune 7" (6:45), "dedh" (1:30), "dhai" (2:30)
        m = re.search(rf"\b(saade|sade|saadhe|sadhe|sawa|sava|paune|pone)\s+{_NUM}\b", t)
        if m:
            base = _num(m.group(2))
            if base is not None:
                if m.group(1).startswith(("sa", "sad")) and m.group(1) not in ("sawa", "sava"):
                    hour, minute = base, 30
                elif m.group(1) in ("sawa", "sava"):
                    hour, minute = base, 15
                else:
                    hour, minute = (base - 1) or 12, 45
        elif re.search(r"\bdedh\b", t):
            hour, minute = 1, 30
        elif re.search(r"\b(?:dhai|dhaai|dhaayi)\b", t):
            hour, minute = 2, 30
    if hour is None:
        m = re.search(r"\b(\d{1,2})\s*[:.]\s*(\d{2})\b", t)
        if m:
            hour, minute = int(m.group(1)), int(m.group(2))
    if hour is None:
        m = re.search(rf"\b{_NUM}\s*(?:baje|baj|bje|o'?clock|oclock|am|pm|a\.m|p\.m|hrs|bajkar|bajke)\b", t)
        if m:
            hour = _num(m.group(1))
            m2 = re.search(rf"\b{_NUM}\s*(?:baje|bje)\s*{_NUM}\s*(?:minute|min|mint)\b", t)
            if m2:
                minute = _num(m2.group(2)) or 0
    if hour is None:
        # bare number after an alarm/time word: "alarm 6 ka", "6 ka alarm"
        m = re.search(rf"\b(?:alarm|at|for|pe|par|ko)\s+{_NUM}\b|\b{_NUM}\s+(?:ka|ke|ki)\s+alarm", t)
        if m:
            hour = _num(m.group(1) or m.group(2))
    if hour is None or not (0 <= hour <= 23) or not (0 <= minute <= 59):
        return None

    explicit = False
    if re.search(_PM, t) or re.search(rf"\b{_EVENING}\b", t):
        explicit = True
        if hour < 12:
            hour += 12
    elif re.search(rf"\b{_NOON}\b", t):
        explicit = True
        if 1 <= hour <= 6:
            hour += 12
    elif re.search(rf"\b{_NIGHT}\b", t):
        explicit = True
        if hour == 12:
            hour = 0
        elif 5 <= hour < 12:
            hour += 12
    elif re.search(rf"\b{_MORNING}\b", t) or re.search(r"\bam\b", t):
        explicit = True
        if hour == 12:
            hour = 0
    elif hour > 12:
        explicit = True

    if not explicit and hour <= 12:
        # choose the sooner of AM/PM (e.g. at 14:00 "7 baje" -> 19:00, at 22:00 -> 07:00)
        am = ClockTime(hour % 12, minute, False, day_hint).next_occurrence(now)
        pm = ClockTime((hour % 12) + 12, minute, False, day_hint).next_occurrence(now)
        hour = (hour % 12) if am <= pm else (hour % 12) + 12
        if day_hint == "tomorrow" and hour >= 12 and not re.search(_PM, t):
            # "kal 7 baje" usually means the morning
            hour -= 12

    return ClockTime(hour, minute, explicit, day_hint)


def parse_duration(text: str) -> int | None:
    """Return seconds, or None."""
    t = _pre(text)
    total = 0
    found = False
    if re.search(r"\b(?:dedh|dedh)\s*(?:ghanta|ghante|hour)\b", t):
        return 90 * 60
    if re.search(r"\b(?:aadha|adha|half an?|half)\s*(?:ghanta|ghante|hour)\b", t):
        return 30 * 60
    if re.search(r"\b(?:dhai)\s*(?:ghanta|ghante|hour)\b", t):
        return 150 * 60
    if re.search(r"\b(?:aadha|adha|half a?)\s*(?:minute|min|minat)\b", t):
        return 30
    for m in re.finditer(rf"\b(\d+(?:\.\d+)?|{_NUM[1:-1]})\s*(ghante|ghanta|ghanton|hours|hour|hrs|hr|h|minutes|minute|minat|mins|min|m|seconds|second|secs|sec|s)\b", t):
        raw = m.group(1)
        try:
            n = float(raw)
        except ValueError:
            n = float(_num(raw) or 0)
        unit = m.group(2)
        if unit.startswith(("ghant", "hour", "hr")) or unit == "h":
            total += int(n * 3600)
        elif unit.startswith(("min", "minat")) or unit == "m":
            total += int(n * 60)
        else:
            total += int(n)
        found = True
    return total if found and total > 0 else None


def describe_clock(hour: int, minute: int) -> str:
    suffix = "AM" if hour < 12 else "PM"
    h = hour % 12 or 12
    return f"{h}:{minute:02d} {suffix}"
