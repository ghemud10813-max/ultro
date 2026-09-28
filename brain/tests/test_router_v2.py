"""Router corpus for Nixin 2.0 commands (routines, reminders, PC control, weather, phone extras, skills…)."""

from __future__ import annotations

from datetime import datetime

import pytest

from nixin.router.router import route

NOW = datetime(2026, 9, 28, 14, 0)


def one(text):
    r = route(text, NOW)
    assert r.intents is not None, f"unresolved: {text!r} (cleaned={r.cleaned!r})"
    assert len(r.intents) == 1, f"expected one intent for {text!r}: {r.intents}"
    return r.intents[0]


def at(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%d %H:%M")


@pytest.mark.parametrize("text,at_,days,actions", [
    ("har raat 11 baje phone silent kar dena", "23:00", [], ["phone silent kar dena"]),
    ("roz subah 7 baje briefing dena", "07:00", [], ["briefing dena"]),
    ("every day at 7 am turn on wifi", "07:00", [], ["turn on wifi"]),
    ("har somvar 9 baje dnd on karo", "09:00", [1], ["dnd on karo"]),
    ("weekdays pe 9 baje yaad dilana ki standup hai", "09:00", [1, 2, 3, 4, 5],
     ["notify: standup hai", "say: Yaad dila raha hoon: standup hai"]),
    ("har roz 4 baje chai ka reminder", "16:00", [], ["notify: chai", "say: Yaad dila raha hoon: chai"]),
    ("har raat 11 baje phone silent karo aur wifi band karo", "23:00", [], ["phone silent karo", "wifi band karo"]),
])
def test_time_routines(text, at_, days, actions):
    it = one(text)
    assert it.kind == "routine_add"
    assert it.params["trigger"] == {"type": "time", "at": at_, "days": days}
    assert it.params["actions"] == actions


def test_one_off_scheduled_command():
    it = one("raat 11 baje phone silent kar dena")
    assert it.kind == "routine_add" and it.params["trigger"]["type"] == "once"
    assert at(it.params["trigger"]["when"]) == "28 23:00" and it.params["actions"] == ["phone silent kar dena"]


@pytest.mark.parametrize("text,trigger,action_start", [
    ("jab battery 20% se kam ho to bata dena", {"event": "battery_low", "below": 20}, "say: Phone ki battery {level}%"),
    ("jab battery full ho jaye to bata dena", {"event": "battery_full", "above": 100}, "say: Phone {level}%"),
    ("jab charger lagaun to brightness full kar dena", {"event": "charging"}, "brightness full kar dena"),
    ("jab mummy ka message aaye to bata dena", {"event": "notification", "contains": "mummy"}, "say: {title} ka {app}"),
    ("jab bhi rahul ka call aaye to bata dena", {"event": "call_incoming", "contains": "rahul"}, "say: {caller}"),
    ("jab whatsapp pe message aaye to bata dena", {"event": "notification", "app": "whatsapp"}, "say: {title}"),
    ("notify me when battery is below 15%", {"event": "battery_low", "below": 15}, "say: Phone battery is at {level}%"),
    ("when rahul calls, tell me", {"event": "call_incoming", "contains": "rahul"}, "say: {caller} is calling."),
])
def test_event_routines(text, trigger, action_start):
    it = one(text)
    assert it.kind == "routine_add"
    assert it.params["trigger"] == {"type": "event", **trigger}
    assert it.params["actions"][0].startswith(action_start)


@pytest.mark.parametrize("text,label,when", [
    ("10 minute baad yaad dilana ki chai bana lu", "chai bana lu", "28 14:10"),
    ("kal subah 8 baje yaad dilana ki meeting hai", "meeting hai", "29 08:00"),
    ("remind me to call mom at 5 pm", "call mom", "28 17:00"),
    ("remind me in 20 minutes to check the oven", "check the oven", "28 14:20"),
    ("remind me to go to the gym at 6 pm", "go to the gym", "28 18:00"),
])
def test_reminders(text, label, when):
    it = one(text)
    assert it.kind == "reminder" and it.params["text"] == label and at(it.params["when"]) == when


def test_reminder_without_time_asks():
    assert one("yaad dilana ki doodh lena hai").kind == "clarify"


def test_recurring_alarm_gets_days():
    it = one("roz 6 baje ka alarm laga do")
    assert it.kind == "alarm" and it.params["hour"] == 6 and it.params["days"] == [1, 2, 3, 4, 5, 6, 7]
    it = one("weekdays pe 7:30 ka alarm laga do")
    assert (it.params["hour"], it.params["minute"], it.params["days"]) == (7, 30, [2, 3, 4, 5, 6])


@pytest.mark.parametrize("text,params", [
    ("PC lock karo", {"action": "lock"}),
    ("laptop ka volume kam karo", {"action": "volume", "mode": "down"}),
    ("pc ka volume 30 percent kar do", {"action": "volume", "mode": "set", "percent": 30}),
    ("PC ka screenshot bhejo", {"action": "screenshot"}),
    ("computer pe youtube kholo", {"action": "open", "target": "youtube"}),
    ("pc pe type karo hello world and bye", {"action": "type", "text": "hello world and bye"}),
    ("PC band kar do", {"action": "shutdown"}),
    ("laptop restart karo", {"action": "restart"}),
    ("shutdown cancel karo", {"action": "cancel_shutdown"}),
    ("PC ka clipboard phone pe bhejo", {"action": "clipboard_to_phone"}),
    ("phone ka clipboard pc pe bhejo", {"action": "clipboard_from_phone"}),
    ("pc ka status batao", {"action": "status"}),
    ("laptop sleep karo", {"action": "sleep"}),
])
def test_pc(text, params):
    it = one(text)
    assert it.kind == "pc"
    for k, v in params.items():
        assert it.params[k] == v, (text, it.params)


def test_pc_and_phone_in_one_command():
    r = route("PC lock karo aur phone silent karo", NOW)
    assert [i.kind for i in r.intents] == ["pc", "phone"]


@pytest.mark.parametrize("text,kind,params", [
    ("Delhi ka mausam kaisa hai", "weather", {"city": "delhi", "when": "now"}),
    ("kal barish hogi?", "weather", {"city": None, "when": "tomorrow", "question": "rain"}),
    ("weather in mumbai", "weather", {"city": "mumbai"}),
    ("briefing do", "briefing", {}),
    ("aaj ka update", "briefing", {}),
    ("mera phone kahan hai", "find_phone", {}),
    ("find my phone", "find_phone", {}),
    ("ringing band karo", "find_phone", {"stop": True}),
    ("phone ki location batao", "locate_phone", {}),
    ("call utha lo", "call_control", {"action": "answer"}),
    ("call kaat do", "call_control", {"action": "end"}),
    ("speaker on karo", "call_control", {"action": "speaker_on"}),
    ("kaunsa gaana chal raha hai", "now_playing", {}),
    ("aaj maine phone kitna chalaya", "usage", {"period": "today"}),
    ("kal ka screen time", "usage", {"period": "yesterday"}),
    ("storage kitna bacha hai", "device_info", {"what": "storage"}),
    ("battery health batao", "device_info", {"what": "battery"}),
    ("auto rotate band karo", "device_setting", {"name": "auto_rotate", "value": False}),
    ("screen timeout 2 minute kar do", "device_setting", {"name": "screen_timeout", "value": 120}),
    ("Rahul ko reply karo: aa raha hoon", "notif_reply", {"who": "Rahul", "text": "aa raha hoon"}),
    ("reply karo ki 5 minute mein aata hoon", "notif_reply", {"who": None, "text": "5 minute mein aata hoon"}),
    ("mere messages summarize karo", "notif_summary", {"app": None}),
    ("whatsapp ke messages ka summary do", "notif_summary", {"app": "whatsapp"}),
    ("notifications clear karo", "notif_clear", {"app": None}),
    ("whatsapp ki notifications clear karo", "notif_clear", {"app": "whatsapp"}),
    ("Rahul wali notification kholo", "notif_open", {"who": "rahul"}),
    ("screen pe kya hai", "screen_read", {"mode": "summary"}),
    ("ye padh ke sunao", "screen_read", {"mode": "read"}),
    ("iska summary do", "screen_read", {"mode": "summary"}),
    ("sikho: chai order", "skill_teach", {"name": "chai order"}),
    ("chai order karna sikho", "skill_teach", {"name": "chai order"}),
    ("save karo", "skill_save", {}),
    ("recording cancel karo", "skill_cancel", {}),
    ("meri skills dikhao", "skill_list", {}),
    ("chai order skill delete karo", "skill_delete", {"name": "chai order"}),
    ("routines dikhao", "routine_list", {}),
    ("reminders dikhao", "routine_list", {"only": "reminders"}),
    ("good night routine chalao", "routine_run", {"name": "good night"}),
    ("low battery alert routine band karo", "routine_toggle", {"name": "low battery alert", "on": False}),
    ("inbox dikhao", "inbox", {"action": "list"}),
    ("ye photo wallpaper laga do", "inbox", {"action": "wallpaper"}),
])
def test_v2_intents(text, kind, params):
    it = one(text)
    assert it.kind == kind, (text, it)
    for k, v in params.items():
        assert it.params.get(k) == v, (text, it.params)


def test_media_seek():
    it = one("gaana aage karo")
    assert it.params == {"method": "media.control", "params": {"action": "seek_forward"}}


@pytest.mark.parametrize("text,kind", [
    ("Rahul ko bol main aa raha hoon", "message"),
    ("6 baje ka alarm laga do", "alarm"),
    ("Rahul ko call karo", "call"),
    ("peeche jao", "phone"),
    ("battery kitni hai", "status"),
    ("instagram kholo", "open_app"),
    ("screenshot le lo", "phone"),
])
def test_v1_commands_unchanged(text, kind):
    assert one(text).kind == kind
