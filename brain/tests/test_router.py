"""Deterministic router corpus: Hinglish + English commands -> intents (no LLM)."""

from __future__ import annotations

from datetime import datetime

import pytest

from nixin.router.normalize import clean, transliterate
from nixin.router.router import route

NOW = datetime(2026, 9, 27, 14, 0)


def one(text):
    r = route(text, NOW)
    assert r.intents is not None, f"unresolved: {text!r} (cleaned={r.cleaned!r})"
    assert len(r.intents) == 1, f"expected one intent for {text!r}: {r.intents}"
    return r.intents[0]


def phone(text):
    it = one(text)
    assert it.kind == "phone", f"{text!r} -> {it}"
    return it.params["method"], it.params["params"]


@pytest.mark.parametrize("text,action,extra", [
    ("volume badha do", "up", {"steps": 2}),
    ("Nixin volume badhao", "up", {}),
    ("thoda volume kam karo", "down", {"steps": 1}),
    ("awaaz kam kar do", "down", {}),
    ("volume bahut zyada badha do", "up", {"steps": 4}),
    ("increase the volume", "up", {}),
    ("volume down", "down", {}),
    ("volume 50 kar do", "set", {"percent": 50}),
    ("set volume to 30%", "set", {"percent": 30}),
    ("volume full kar do", "max", {}),
    ("mute karo", "mute", {}),
    ("unmute", "unmute", {}),
    ("volume 3 step badhao", "up", {"steps": 3}),
    ("वॉल्यूम बढ़ा दो", "up", {}),
])
def test_volume(text, action, extra):
    m, p = phone(text)
    assert m == "device.volume" and p["action"] == action
    for k, v in extra.items():
        assert p[k] == v


def test_volume_streams():
    assert phone("ringtone volume kam karo")[1]["stream"] == "ring"
    assert phone("alarm volume full")[1]["stream"] == "alarm"
    assert phone("volume badhao")[1]["stream"] == "media"


@pytest.mark.parametrize("text,on", [
    ("torch on karo", True), ("torch jala do", True), ("flashlight on", True), ("turn on the flashlight", True),
    ("torch band karo", False), ("torch off kar do", False), ("flash light bujha do", False), ("टॉर्च ऑन करो", True),
])
def test_torch(text, on):
    assert phone(text) == ("device.torch", {"on": on})


@pytest.mark.parametrize("text,action", [
    ("peeche jao", "back"), ("back", "back"), ("go back", "back"), ("home pe jao", "home"), ("home screen", "home"),
    ("recent apps dikhao", "recents"), ("notification panel kholo", "notifications"), ("quick settings kholo", "quick_settings"),
    ("phone lock kar do", "lock_screen"), ("screenshot lo", "screenshot"), ("take a screenshot", "screenshot"),
])
def test_global(text, action):
    assert phone(text) == ("device.global", {"action": action})


@pytest.mark.parametrize("text,mode", [
    ("phone silent kar do", "silent"), ("silent mode on karo", "silent"), ("vibrate pe daal do", "vibrate"),
    ("silent hatao", "normal"), ("general mode", "normal"),
])
def test_ringer(text, mode):
    assert phone(text) == ("device.ringer", {"mode": mode})


def test_dnd_brightness():
    assert phone("dnd on karo") == ("device.dnd", {"on": True})
    assert phone("do not disturb band karo") == ("device.dnd", {"on": False})
    assert phone("brightness full kar do") == ("device.brightness", {"action": "set", "percent": 100})
    assert phone("brightness kam karo") == ("device.brightness", {"action": "down"})
    assert phone("brightness 40 percent") == ("device.brightness", {"action": "set", "percent": 40})
    assert phone("auto brightness on") == ("device.brightness", {"action": "auto"})


@pytest.mark.parametrize("text,setting,on", [
    ("wifi on karo", "wifi", True), ("wifi band kar do", "wifi", False), ("bluetooth chalu karo", "bluetooth", True),
    ("turn off bluetooth", "bluetooth", False), ("mobile data on karo", "mobile_data", True), ("hotspot on", "hotspot", True),
    ("location band karo", "location", False), ("airplane mode on karo", "airplane", True),
])
def test_toggles(text, setting, on):
    it = one(text)
    assert it.kind == "toggle" and it.params == {"setting": setting, "on": on}


def test_settings_panels():
    assert phone("wifi settings kholo") == ("device.settings", {"panel": "wifi"})
    assert phone("settings kholo") == ("device.settings", {"panel": "main"})
    assert phone("battery settings open karo") == ("device.settings", {"panel": "battery"})


@pytest.mark.parametrize("text,action", [
    ("gaana chalao", "play"), ("music pause karo", "pause"), ("gaana band karo", "pause"), ("next song", "next"),
    ("agla gaana", "next"), ("pichla gaana chalao", "previous"), ("pause", "pause"), ("play music", "play"), ("skip", "next"),
])
def test_media(text, action):
    assert phone(text) == ("media.control", {"action": action})


@pytest.mark.parametrize("text,name", [
    ("WhatsApp kholo", "whatsapp"), ("instagram khol do", "instagram"), ("open youtube", "youtube"),
    ("camera open karo", "camera"), ("launch spotify", "spotify"), ("insta kholo", "instagram"), ("google pay kholo", "google pay"),
])
def test_open_app(text, name):
    it = one(text)
    assert it.kind == "open_app" and it.params["name"] == name


@pytest.mark.parametrize("text,channel,who,body", [
    ("WhatsApp pe Rahul ko bol main 10 min late hoon", "whatsapp", "Rahul", "main 10 min late hoon"),
    ("Rahul ko WhatsApp pe bolo ki main aa raha hoon", "whatsapp", "Rahul", "main aa raha hoon"),
    ("mummy ko message bhejo ki khana bana do", "default", "mummy", "khana bana do"),
    ("Rahul ko whatsapp kar do ki kal milte hain", "whatsapp", "Rahul", "kal milte hain"),
    ("mere bhai ko bol do: Happy Birthday!", "default", "bhai", "Happy Birthday!"),
    ("Priya ko sms bhejo ki call back karna", "sms", "Priya", "call back karna"),
    ("send a whatsapp to Rahul saying I'm running late", "whatsapp", "Rahul", "I'm running late"),
    ("tell mom on whatsapp that I'll be home by 9", "whatsapp", "mom", "I'll be home by 9"),
    ("text Amit: meeting at 5", "sms", "Amit", "meeting at 5"),
    ("send hi to Rahul on whatsapp", "whatsapp", "Rahul", "hi"),
    ("Nixin, Rahul Sharma ko bolo ki aaj nahi aa paunga aur sorry", "default", "Rahul Sharma", "aaj nahi aa paunga aur sorry"),
])
def test_messages(text, channel, who, body):
    it = one(text)
    assert it.kind == "message", it
    assert it.params == {"channel": channel, "who": who, "body": body}
    assert it.external


@pytest.mark.parametrize("text,who", [
    ("Rahul ko call karo", "rahul"), ("mummy ko phone lagao", "mummy"), ("call Amit", "amit"),
    ("dial 9876543210", "9876543210"), ("papa ko call kar do", "papa"),
])
def test_calls(text, who):
    it = one(text)
    assert it.kind == "call" and it.params["who"] == who


def test_call_false_positives():
    r = route("call history dikhao", NOW)
    assert not r.intents or r.intents[0].kind != "call"


@pytest.mark.parametrize("text,hour,minute", [
    ("kal subah 6 baje ka alarm laga do", 6, 0), ("6:30 ka alarm set karo", 18, 30), ("alarm lagao saade 7 baje subah", 7, 30),
    ("wake me up at 7 am", 7, 0), ("raat 11 baje alarm", 23, 0), ("10 minute baad alarm laga do", 14, 10),
    ("subah 5 baje utha dena", 5, 0),
])
def test_alarm(text, hour, minute):
    it = one(text)
    assert it.kind == "alarm" and (it.params["hour"], it.params["minute"]) == (hour, minute)


def test_alarm_needs_time():
    it = one("alarm laga do")
    assert it.kind == "clarify"


def test_reminder_becomes_labelled_alarm():
    it = one("shaam 5 baje yaad dilana ki doctor ke paas jana hai")
    assert it.kind == "alarm" and it.params["hour"] == 17 and "doctor" in it.params["label"]


@pytest.mark.parametrize("text,secs", [("5 minute ka timer lagao", 300), ("set a timer for 90 seconds", 90), ("dedh ghante ka timer", 5400)])
def test_timer(text, secs):
    it = one(text)
    assert it.kind == "timer" and it.params["seconds"] == secs


@pytest.mark.parametrize("text,engine,query,play", [
    ("youtube pe arijit singh songs chalao", "youtube", "arijit singh songs", True),
    ("youtube par cooking videos search karo", "youtube", "cooking videos", False),
    ("play believer on youtube", "youtube", "believer", True),
    ("google pe weather delhi search karo", "web", "weather delhi", False),
    ("search for best pizza near me", "web", "best pizza near me", False),
    ("ipl score google karo", "web", "ipl score", False),
    ("play store pe zomato dhundo", "playstore", "zomato", False),
    ("spotify pe lofi chalao", "spotify", "lofi", True),
    ("arijit ke gaane chalao", "youtube", "arijit songs", True),
])
def test_search(text, engine, query, play):
    it = one(text)
    assert it.kind == "search" and it.params == {"engine": engine, "query": query, "play": play}


def test_navigate():
    it = one("india gate ka rasta dikhao")
    assert it.kind == "navigate" and it.params["destination"] == "india gate"
    assert one("navigate to connaught place").params["destination"] == "connaught place"


def test_notifications_and_status():
    it = one("meri latest notification padh ke bata")
    assert it.kind == "notifications" and it.params == {"app": None, "limit": 1}
    it = one("instagram ki notification padho")
    assert it.kind == "notifications" and it.params["app"] == "instagram"
    assert one("battery kitni hai").kind == "status"
    assert one("phone ki battery batao").params == {"what": "battery"}
    assert one("time kya hua").params == {"what": "time"}


def test_chat_cancel_remember():
    assert one("hello").params["kind"] == "greet"
    assert one("thank you").params["kind"] == "thanks"
    assert one("ruk ja").kind == "cancel"
    assert one("stop").kind == "cancel"
    it = one("yaad rakhna ki meri car ka number DL 3C 1234 hai")
    assert it.kind == "remember" and it.params["fact"] == "meri car ka number DL 3C 1234 hai"


def test_multi_intent():
    r = route("torch on karo aur volume full kar do", NOW)
    assert [i.kind for i in r.intents] == ["phone", "phone"]
    assert r.intents[0].params["method"] == "device.torch"
    assert r.intents[1].params["params"]["action"] == "max"


def test_open_then_notifications_carries_app():
    r = route("Instagram khol aur latest notification padh ke bata", NOW)
    assert [i.kind for i in r.intents] == ["open_app", "notifications"]
    assert r.intents[1].params["app"] == "instagram"


def test_message_body_with_aur_not_split():
    r = route("Rahul ko bolo ki main aur Priya aa rahe hain", NOW)
    assert len(r.intents) == 1 and r.intents[0].params["body"] == "main aur Priya aa rahe hain"


@pytest.mark.parametrize("text", [
    "Instagram pe sabse latest post like karo",
    "mere last 3 whatsapp messages summarize karo",
    "zomato se ek pizza order kar do",
    "settings mein jaake dark mode on karo",
    "what's the capital of France",
    "Rahul ko video call karo",
])
def test_unresolved_goes_to_llm(text):
    r = route(text, NOW)
    assert r.intents is None, f"{text!r} should need the LLM, got {r.intents}"


def test_normalisation():
    assert clean("Hey Nixin, volume badha do!") == "volume badha do"
    assert transliterate("वॉल्यूम बढ़ा दो").startswith("vol")
    assert clean("व्हाट्सएप खोलो") == "whatsapp kholo" or "kholo" in clean("व्हाट्सएप खोलो")
