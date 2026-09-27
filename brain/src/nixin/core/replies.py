"""Short spoken replies in Hinglish or English."""

from __future__ import annotations

_T: dict[str, tuple[str, str]] = {
    # key: (hinglish, english)
    "volume": ("Volume {current}/{max} pe hai.", "Volume is at {current} of {max}."),
    "volume_mute": ("Mute kar diya.", "Muted."),
    "torch_on": ("Torch on kar di.", "Flashlight on."),
    "torch_off": ("Torch band kar di.", "Flashlight off."),
    "brightness": ("Brightness {current}% kar di.", "Brightness set to {current}%."),
    "brightness_auto": ("Auto brightness on kar di.", "Auto brightness on."),
    "ringer": ("Phone ab {mode} mode pe hai.", "Ringer set to {mode}."),
    "dnd_on": ("Do Not Disturb on.", "Do Not Disturb is on."),
    "dnd_off": ("Do Not Disturb band.", "Do Not Disturb is off."),
    "global_back": ("Peeche chala gaya.", "Went back."),
    "global_home": ("Home screen pe hoon.", "Home screen."),
    "global_recents": ("Recent apps khol diye.", "Showing recent apps."),
    "global_notifications": ("Notifications khol di.", "Opened notifications."),
    "global_quick_settings": ("Quick settings khol di.", "Opened quick settings."),
    "global_lock_screen": ("Phone lock kar diya.", "Phone locked."),
    "global_screenshot": ("Screenshot le liya.", "Screenshot taken."),
    "global_power_dialog": ("Power menu khol diya.", "Opened the power menu."),
    "global_split_screen": ("Split screen kar diya.", "Split screen on."),
    "settings": ("{panel} settings khol di.", "Opened {panel} settings."),
    "media_play": ("Chala diya.", "Playing."),
    "media_pause": ("Ruk gaya.", "Paused."),
    "media_toggle": ("Theek hai.", "Done."),
    "media_next": ("Agla chala diya.", "Next track."),
    "media_previous": ("Pichla chala diya.", "Previous track."),
    "media_stop": ("Band kar diya.", "Stopped."),
    "app_opened": ("{label} khol diya.", "Opened {label}."),
    "app_not_found": ("'{name}' naam ka app nahi mila.", "I couldn't find an app called '{name}'."),
    "alarm": ("Alarm {time} ke liye laga diya{when}.", "Alarm set for {time}{when}."),
    "alarm_today_warning": (" — dhyan do, yeh aaj hi bajega", " — note: it will ring today"),
    "timer": ("{duration} ka timer shuru.", "Timer for {duration} started."),
    "search": ("{engine} pe '{query}' search kar diya.", "Searched '{query}' on {engine}."),
    "navigate": ("{destination} ka rasta khol diya.", "Navigation to {destination} started."),
    "called": ("{name} ko call laga diya.", "Calling {name}."),
    "dialed": ("{name} ka number dialer mein khol diya.", "Opened the dialer for {name}."),
    "message_sent": ("{name} ko {channel} pe bhej diya: \"{body}\"", "Sent to {name} on {channel}: \"{body}\""),
    "message_composer": ("{channel} mein message likh diya hai, Send tum dabao.", "The message is ready in {channel}; tap Send."),
    "message_uncertain": ("Message shayad gaya hai, pakka confirm nahi ho paya. Dobara nahi bhej raha.",
                          "The message may have been sent but I couldn't confirm it. I won't resend it."),
    "confirm_message": ("{name} ko {channel} pe bhejun: \"{body}\"?", "Send to {name} on {channel}: \"{body}\"?"),
    "confirm_call": ("{name} ({number}) ko call karun?", "Call {name} ({number})?"),
    "confirm_generic": ("Yeh karun: {what}?", "Should I {what}?"),
    "declined": ("Theek hai, nahi kiya.", "Okay, cancelled."),
    "no_answer": ("Jawab nahi mila, isliye cancel kar diya.", "No answer, so I cancelled it."),
    "contact_not_found": ("'{name}' contacts mein nahi mila.", "I couldn't find '{name}' in your contacts."),
    "contact_choose": ("Kaunsa {name}?", "Which {name}?"),
    "no_number": ("{name} ka koi number nahi hai.", "{name} has no phone number."),
    "notif_none": ("Koi nayi notification nahi hai.", "No new notifications."),
    "notif_none_app": ("{app} ki koi notification nahi hai.", "No notifications from {app}."),
    "battery": ("Battery {level}% hai{charging}.", "Battery is at {level}%{charging}."),
    "battery_charging": (", charging ho rahi hai", " and charging"),
    "time": ("Abhi {time} baje hain.", "It's {time}."),
    "date": ("Aaj {date} hai.", "Today is {date}."),
    "remembered": ("Yaad rakh liya.", "Got it, I'll remember that."),
    "alias_set": ("Theek hai, '{alias}' matlab {name}.", "Okay, '{alias}' means {name}."),
    "greet": ("Namaste! Bolo, kya karna hai?", "Hi! What can I do?"),
    "thanks": ("Koi baat nahi!", "You're welcome!"),
    "howareyou": ("Main badhiya! Aap batao, kya karun?", "I'm great! What should I do?"),
    "intro": ("Main Nixin hoon — tumhare phone ko chala sakta hoon: apps kholna, message, call, alarm, volume, torch, notifications, aur multi-step kaam bhi.",
              "I'm Nixin — I operate your phone: open apps, messages, calls, alarms, volume, torch, notifications and multi-step tasks."),
    "cancelled": ("Ruk gaya.", "Stopped."),
    "nothing_running": ("Abhi kuch chal nahi raha.", "Nothing is running."),
    "busy": ("Ek kaam chal raha hai, pehle woh khatam hone do ya 'ruk ja' bolo.", "I'm busy with a task; say 'stop' to cancel it."),
    "offline": ("Phone connected nahi hai. Phone pe Nixin app kholo.", "The phone isn't connected. Open the Nixin app on your phone."),
    "stopped": ("Phone pe kill switch on hai. Phone se Resume karo.", "The kill switch is on. Resume from the phone."),
    "blocked": ("Yeh app safety ke liye blocked hai (banking/UPI/password).", "That app is blocked for safety (banking/UPI/passwords)."),
    "locked": ("Phone locked hai, pehle unlock karo.", "Your phone is locked; unlock it first."),
    "permission": ("Phone pe permission chahiye: {what}.", "I need a permission on the phone: {what}."),
    "not_understood": ("Samajh nahi aaya. Dobara bolo?", "Sorry, I didn't get that. Could you rephrase?"),
    "llm_off": ("Yeh command samajhne ke liye AI chahiye, par koi LLM key set nahi hai.", "I need an AI model for that, but no LLM key is configured."),
    "llm_busy": ("AI models abhi busy hain (free limit). Thodi der baad try karo.", "The AI models are busy (free-tier limit). Try again shortly."),
    "failed": ("Nahi ho paya: {reason}", "Couldn't do it: {reason}"),
    "done": ("Ho gaya.", "Done."),
    "toggle_done": ("{setting} {state} kar diya.", "{setting} turned {state}."),
    "toggle_already": ("{setting} pehle se {state} hai.", "{setting} is already {state}."),
    "toggle_panel": ("{setting} ka panel khol diya, toggle dabao.", "Opened the {setting} panel; flip the toggle."),
    "working": ("Kar raha hoon…", "On it…"),
}


def say(key: str, lang: str = "hinglish", **kw) -> str:
    hi, en = _T.get(key, (key, key))
    tmpl = en if lang == "english" else hi
    try:
        return tmpl.format(**kw)
    except (KeyError, IndexError):
        return tmpl


def duration_text(seconds: int, lang: str = "hinglish") -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h} {'ghante' if lang != 'english' else 'hour' + ('s' if h > 1 else '')}")
    if m:
        parts.append(f"{m} {'minute' if lang != 'english' else 'minute' + ('s' if m > 1 else '')}")
    if s:
        parts.append(f"{s} {'second' if lang != 'english' else 'second' + ('s' if s > 1 else '')}")
    return " ".join(parts) or "0"
