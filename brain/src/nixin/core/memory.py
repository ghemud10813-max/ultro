"""User memory: contact nicknames, app aliases, remembered facts, short conversation.

Deliberately small and explicit. Nothing here is sent to an LLM unless it is needed
for the current command (aliases + a handful of facts + the last few turns).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from nixin.core.store import Store

# Common apps: alias -> candidate packages (first installed one wins).
BUILTIN_APPS: dict[str, list[str]] = {
    "whatsapp": ["com.whatsapp", "com.whatsapp.w4b"],
    "whatsapp business": ["com.whatsapp.w4b"],
    "instagram": ["com.instagram.android"],
    "youtube": ["com.google.android.youtube"],
    "youtube music": ["com.google.android.apps.youtube.music"],
    "yt music": ["com.google.android.apps.youtube.music"],
    "chrome": ["com.android.chrome", "com.sec.android.app.sbrowser"],
    "browser": ["com.android.chrome", "com.sec.android.app.sbrowser"],
    "internet": ["com.sec.android.app.sbrowser", "com.android.chrome"],
    "camera": ["com.sec.android.app.camera", "com.google.android.GoogleCamera", "com.android.camera", "com.android.camera2"],
    "gallery": ["com.sec.android.gallery3d", "com.google.android.apps.photos", "com.miui.gallery"],
    "photos": ["com.google.android.apps.photos", "com.sec.android.gallery3d"],
    "settings": ["com.android.settings"],
    "maps": ["com.google.android.apps.maps"],
    "google maps": ["com.google.android.apps.maps"],
    "gmail": ["com.google.android.gm"],
    "mail": ["com.google.android.gm", "com.samsung.android.email.provider"],
    "play store": ["com.android.vending"],
    "playstore": ["com.android.vending"],
    "calculator": ["com.sec.android.app.popupcalculator", "com.google.android.calculator", "com.miui.calculator"],
    "clock": ["com.sec.android.app.clockpackage", "com.google.android.deskclock", "com.android.deskclock"],
    "alarm": ["com.sec.android.app.clockpackage", "com.google.android.deskclock"],
    "calendar": ["com.samsung.android.calendar", "com.google.android.calendar"],
    "contacts": ["com.samsung.android.app.contacts", "com.google.android.contacts"],
    "phone": ["com.samsung.android.dialer", "com.google.android.dialer", "com.android.dialer"],
    "dialer": ["com.samsung.android.dialer", "com.google.android.dialer", "com.android.dialer"],
    "messages": ["com.samsung.android.messaging", "com.google.android.apps.messaging"],
    "sms": ["com.samsung.android.messaging", "com.google.android.apps.messaging"],
    "files": ["com.sec.android.app.myfiles", "com.google.android.apps.nbu.files"],
    "my files": ["com.sec.android.app.myfiles"],
    "spotify": ["com.spotify.music"],
    "telegram": ["org.telegram.messenger"],
    "snapchat": ["com.snapchat.android"],
    "facebook": ["com.facebook.katana"],
    "messenger": ["com.facebook.orca"],
    "twitter": ["com.twitter.android"],
    "x": ["com.twitter.android"],
    "linkedin": ["com.linkedin.android"],
    "netflix": ["com.netflix.mediaclient"],
    "hotstar": ["in.startv.hotstar"],
    "jiohotstar": ["in.startv.hotstar"],
    "prime video": ["com.amazon.avod.thirdpartyclient"],
    "amazon": ["in.amazon.mShop.android.shopping", "com.amazon.mShop.android.shopping"],
    "flipkart": ["com.flipkart.android"],
    "zomato": ["com.application.zomato"],
    "swiggy": ["in.swiggy.android"],
    "uber": ["com.ubercab"],
    "ola": ["com.olacabs.customer"],
    "keep": ["com.google.android.keep"],
    "notes": ["com.samsung.android.app.notes", "com.google.android.keep"],
    "samsung notes": ["com.samsung.android.app.notes"],
    "google": ["com.google.android.googlequicksearchbox"],
    "drive": ["com.google.android.apps.docs"],
    "meet": ["com.google.android.apps.tachyon", "com.google.android.apps.meetings"],
    "zoom": ["us.zoom.videomeetings"],
    "truecaller": ["com.truecaller"],
    "shazam": ["com.shazam.android"],
    "discord": ["com.discord"],
    "reddit": ["com.reddit.frontpage"],
    "pinterest": ["com.pinterest"],
    "clash of clans": ["com.supercell.clashofclans"],
    "bgmi": ["com.pubg.imobile"],
}


@dataclass
class AppMatch:
    package: str
    label: str
    score: float


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def match_app(name: str, apps: list[dict], aliases: dict[str, str] | None = None) -> AppMatch | None:
    """Resolve a spoken app name against the phone's installed launchable apps."""
    n = _norm(name)
    n = re.sub(r"\s+app$", "", n)
    if not n:
        return None
    by_pkg = {a["package"]: a.get("label") or a["package"] for a in apps}
    if aliases and n in aliases:
        pkg = aliases[n]
        return AppMatch(pkg, by_pkg.get(pkg, n), 1.0)
    for pkg in BUILTIN_APPS.get(n, []):
        if pkg in by_pkg or not apps:
            return AppMatch(pkg, by_pkg.get(pkg, name), 0.99)
    best: AppMatch | None = None
    for a in apps:
        label = _norm(a.get("label") or "")
        if not label:
            continue
        if label == n:
            return AppMatch(a["package"], a["label"], 1.0)
        score = difflib.SequenceMatcher(None, n, label).ratio()
        if label.startswith(n) or n.startswith(label):
            score = max(score, 0.86)
        if n in label.split() or any(w == n for w in label.split()):
            score = max(score, 0.84)
        if best is None or score > best.score:
            best = AppMatch(a["package"], a["label"], score)
    return best if best and best.score >= 0.8 else None


class Memory:
    def __init__(self, store: Store) -> None:
        self.store = store

    # contacts
    def contact_alias(self, who: str) -> dict | None:
        return self.store.get_contact_alias(who)

    def set_contact_alias(self, alias: str, contact_name: str, number: str | None = None) -> None:
        self.store.set_contact_alias(alias, contact_name, number)

    # apps
    def app_aliases(self) -> dict[str, str]:
        return {r["alias"]: r["package"] for r in self.store.list_app_aliases()}

    # facts
    def remember(self, fact: str) -> None:
        self.store.add_fact(fact)

    def facts(self, limit: int = 12) -> list[str]:
        return [f["text"] for f in self.store.list_facts(limit)]

    def relevant_facts(self, text: str, limit: int = 6) -> list[str]:
        words = {w for w in re.findall(r"[a-z0-9]{3,}", text.lower())}
        scored = []
        for f in self.facts(60):
            fw = set(re.findall(r"[a-z0-9]{3,}", f.lower()))
            scored.append((len(words & fw), f))
        scored.sort(key=lambda x: -x[0])
        top = [f for s, f in scored if s > 0][:limit]
        return top or self.facts(3)

    # conversation
    def add_turn(self, role: str, text: str, task_id: str | None = None) -> None:
        self.store.add_turn(role, text, task_id)

    def recent(self, n: int = 6) -> list[dict]:
        return self.store.recent_turns(n)

    def prompt_block(self, text: str, history_turns: int = 6) -> str:
        """Compact memory context for LLM prompts."""
        lines: list[str] = []
        aliases = self.store.list_contact_aliases()
        if aliases:
            lines.append("Contact nicknames: " + "; ".join(f"{a['alias']} = {a['contact_name']}" for a in aliases[:15]))
        facts = self.relevant_facts(text)
        if facts:
            lines.append("Things the user told you to remember: " + " | ".join(facts))
        turns = self.recent(history_turns)
        if turns:
            lines.append("Recent conversation:\n" + "\n".join(f"{t['role']}: {t['text'][:200]}" for t in turns))
        return "\n".join(lines)
