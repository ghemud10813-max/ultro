"""Text normalisation for routing Hinglish / English commands.

* Devanagari is transliterated to rough Roman Hinglish (only for matching —
  message bodies are always taken from the original text).
* Wake words, fillers and punctuation are removed.
* Common spelling variants are unified ("whatsap" -> "whatsapp").
"""

from __future__ import annotations

import re
import unicodedata

_VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri", "ए": "e", "ऐ": "ai",
    "ओ": "o", "औ": "au", "ऑ": "o", "ऍ": "e",
}
_MATRAS = {
    "ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri", "े": "e", "ै": "ai", "ो": "o",
    "ौ": "au", "ॉ": "o", "ॅ": "e",
}
_CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh",
    "ञ": "n", "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d",
    "ध": "dh", "न": "n", "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r",
    "ल": "l", "व": "v", "श": "sh", "ष": "sh", "स": "s", "ह": "h",
}
_NUKTA = {"क": "q", "ख": "kh", "ग": "g", "ज": "z", "ड": "d", "ढ": "dh", "फ": "f", "य": "y"}
_DIGITS = {chr(0x0966 + i): str(i) for i in range(10)}
_VIRAMA, _NUKTA_SIGN, _ANUSVARA, _CHANDRABINDU, _VISARGA = "्", "़", "ं", "ँ", "ः"


def has_devanagari(text: str) -> bool:
    return any("ऀ" <= ch <= "ॿ" for ch in text)


def transliterate(text: str) -> str:
    """Very small Devanagari -> Roman Hinglish transliterator (good enough for matching)."""
    if not has_devanagari(text):
        return text
    text = unicodedata.normalize("NFC", text)
    # pre-composed nukta letters -> base + nukta
    text = unicodedata.normalize("NFD", text).replace("़", _NUKTA_SIGN)
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in _CONSONANTS:
            base = _CONSONANTS[ch]
            j = i + 1
            if j < n and text[j] == _NUKTA_SIGN:
                base = _NUKTA.get(ch, base)
                j += 1
            if j < n and text[j] in _MATRAS:
                out.append(base + _MATRAS[text[j]])
                j += 1
            elif j < n and text[j] == _VIRAMA:
                out.append(base)
                j += 1
            else:
                out.append(base + "a")
            i = j
        elif ch in _VOWELS:
            out.append(_VOWELS[ch])
            i += 1
        elif ch in (_ANUSVARA, _CHANDRABINDU):
            out.append("n")
            i += 1
        elif ch == _VISARGA:
            out.append("h")
            i += 1
        elif ch in _DIGITS:
            out.append(_DIGITS[ch])
            i += 1
        elif ch in ("।", "॥"):
            out.append(".")
            i += 1
        elif ch in (_NUKTA_SIGN, _VIRAMA) or ch in _MATRAS:
            out.append(_MATRAS.get(ch, ""))
            i += 1
        else:
            out.append(ch)
            i += 1
    roman = "".join(out)

    def fix_word(m: re.Match) -> str:
        w = m.group(0)
        # schwa deletion at word end ("kara" -> "kar"), keep short words like "na"
        if len(w) > 2 and w.endswith("a") and not w.endswith("aa") and w[-2] not in "aeiou":
            w = w[:-1]
        if w.endswith("aa"):
            w = w[:-1]
        if w.endswith("ee"):
            w = w[:-2] + "i"
        if w.endswith("oo"):
            w = w[:-2] + "u"
        return w

    return re.sub(r"[a-z]+", fix_word, roman)


_WAKE = re.compile(r"^\s*(?:(?:hey|hi|ok|okay|oye|arre|are|suno|sun)\s+)?nixin\b[\s,!.:-]*", re.I)
_FILLERS = re.compile(
    r"\b(?:please|plz|pls|kripya|zara|jara|jaldi se|jaldi|ek baar|ekbar|bhai please|yaar)\b", re.I
)
_VARIANTS: list[tuple[re.Pattern, str]] = [
    (re.compile(p, re.I), r)
    for p, r in [
        (r"\b(?:whats\s*app|whatsap|watsapp|watsap|whatapp|votsaip|vhatsap|vatsap|wtsp|wa)\b", "whatsapp"),
        (r"\b(?:insta|instagram|instgram|instagrm)\b", "instagram"),
        (r"\b(?:yt|you\s*tube|yutub|yutyub|youtub)\b", "youtube"),
        (r"\b(?:volyum|volyoom|valume|volum|vollume)\b", "volume"),
        (r"\b(?:tarch|torche|flash\s*light|flashlite)\b", "torch"),
        (r"\b(?:alaram|alarum|alarm)\b", "alarm"),
        (r"\b(?:massage|mesage|messege|mssg|msg)\b", "message"),
        (r"\b(?:fone|phon)\b", "phone"),
        (r"\b(?:blutooth|bluetoth|blue\s*tooth)\b", "bluetooth"),
        (r"\b(?:wi-?fi|wai\s*fai|vaifai)\b", "wifi"),
        (r"\b(?:notifications|notifikeshan|notification)\b", "notification"),
        (r"\b(?:screen\s*shot|skrinshot)\b", "screenshot"),
        (r"\b(?:brightnes|braitness|brightness)\b", "brightness"),
    ]
]


def clean(text: str) -> str:
    """Normalise for matching: transliterate, lowercase, drop wake word/fillers/punctuation."""
    t = transliterate(text)
    t = unicodedata.normalize("NFKC", t).lower()
    t = t.replace("’", "'").replace("‘", "'")
    t = _WAKE.sub("", t)
    for pat, rep in _VARIANTS:
        t = pat.sub(rep, t)
    t = _FILLERS.sub(" ", t)
    # keep letters, digits, spaces, ':', '.', '%', '+', "'" (for times, percents, numbers)
    t = re.sub(r"[^\w\s:.%+']", " ", t)
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)  # dots only inside numbers (6.30)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def strip_wake(text: str) -> str:
    """Remove a leading wake word from the ORIGINAL text (keeps case/punctuation)."""
    return _WAKE.sub("", text).strip()
