# Nixin 2.0 — what you can do

Everything below works by **voice** (PC push-to-talk, phone mic, wake word), **typing** (PC console, dashboard, phone
chat) or from the **dashboard**. Hinglish and English both work; Devanagari is transliterated. Commands marked 🧠 go
through the LLM only if the deterministic router doesn't catch your wording — most of these never need an AI call.

---

## 1. Routines & scenes — Nixin acts on its own

| Say | What happens |
|---|---|
| `har raat 11 baje phone silent kar dena` | daily routine at 23:00 → ringer silent |
| `roz subah 7 baje briefing dena` | daily briefing at 7:00 |
| `har somvar 9 baje dnd on karo` · `weekdays pe 9 baje yaad dilana ki standup hai` | weekday routines |
| `raat 11 baje phone silent kar dena` | one-off scheduled command (no "har/roz") |
| `jab battery 20% se kam ho to bata dena` | event routine: spoken alert on PC + phone |
| `jab charger lagaun to brightness full kar dena` | charger event → command |
| `jab Mummy ka message aaye to bata dena` · `jab whatsapp pe message aaye to bata dena` | notification event (needs *Mirror notifications*) |
| `jab bhi Rahul ka call aaye to bata dena` · `when rahul calls, tell me` | incoming-call event |
| `good night` · `study mode` · `meeting mode` · `good morning` | built-in **scenes** (DND, brightness, music, briefing…) |
| `routines dikhao` · `reminders dikhao` · `good night routine chalao` · `low battery alert routine band karo` · `X routine delete karo` | manage them |

Routine actions are ordinary Nixin commands plus `say: …` (speak), `notify: …` (phone + PC notification) and
`wait: 5`. Placeholders from the event: `{level} {app} {title} {text} {caller} {ssid} {time} {name}`.
The dashboard's **Automations** tab edits everything (time/event/phrase/interval/once triggers, weekdays, cooldown).

**Safety:** routine commands run with source `routine`. Messages and calls inside a routine still **ask you** (phone
dialog + dashboard) unless you mark that routine **Trusted** on the dashboard.

## 2. Reminders

`10 minute baad yaad dilana ki chai bana lu` · `kal subah 8 baje yaad dilana ki meeting hai` ·
`remind me to call mom at 5 pm` · `remind me in 20 minutes to check the oven`

At the time: a phone notification + spoken reminder. Reminders live on the PC (the PC must be running); for
something that must ring even if the PC is off, use an **alarm**: `roz 6 baje ka alarm laga do` (repeating alarms
are set on the phone's clock app).

## 3. Teach mode — Nixin learns by watching you

1. `sikho: chai order` (or `chai order karna sikho`) → the phone shows *"Nixin is learning…"*
2. Do the task on the phone once (open the app, tap, type…).
3. `save karo` (or tap **Save** in the notification).
4. Later: `chai order chalao` → replayed step by step, checking each element is on screen first. No LLM.
5. `swiggy search: biryani` → the first thing you typed while teaching is replaced by `biryani`.

If a replay breaks (the app changed), the AI agent takes over from the current screen with the remaining steps as a
hint. `meri skills dikhao`, `chai order skill delete karo`.

**Auto-learned routes:** when the agent finishes a UI task (e.g. *settings mein dark mode on karo*), the route it took
is saved. Next time the same goal is replayed directly — fast and zero tokens. Toggle *Auto-replay learned routes*
on the dashboard. Passwords and blocked apps are never recorded.

## 4. Notifications, smarter

| Say | |
|---|---|
| `Rahul ko reply karo: aa raha hoon` | replies through WhatsApp/Telegram/SMS's **own reply button** — no app opening. Falls back to a normal message when there's no notification from Rahul |
| `reply karo ki 5 minute mein aata hoon` | replies to the latest repliable notification |
| `mere messages summarize karo` · `whatsapp ke messages ka summary do` · `maine kya miss kiya` | short summary (LLM when available, grouped list otherwise) |
| `notifications clear karo` · `instagram ki notifications clear karo` · `Rahul wali notification kholo` | manage them |

Turn on **Settings → Mirror notifications** on the phone for the live feed: new notifications appear on the dashboard
(reply/open/dismiss buttons), optionally as PC desktop toasts, and messages from your **VIP** list are read aloud
("Mummy ka WhatsApp pe message: khana kha liya?"). VIPs: dashboard → Notifications, or `[notifications] vip` in
`nixin.toml`. OTP-like text is masked on the phone before anything leaves it.

## 5. PC ⇄ phone bridge

- **Phone → PC:** Share → **Send to PC (Nixin)** on any text, link, photo, video or file. Text/links land on the PC
  clipboard (and optionally open in the browser); files land in `~/Nixin Inbox`. `inbox dikhao` lists them.
- **PC → phone:** drag files onto the dashboard's **Files** tab → phone `Downloads/Nixin`. `PC ka screenshot bhejo`.
- **Clipboard:** `PC ka clipboard phone pe bhejo` · `phone ka clipboard pc pe bhejo` (Android only lets Nixin read
  the phone clipboard while the app is open — sharing text is the reliable way).
- **Wallpaper:** share a photo to Nixin, then `ye photo wallpaper laga do` — or drop an image on the dashboard.

## 6. Control the PC (from the phone or the PC)

`PC lock karo` · `laptop sleep karo` · `PC band kar do` / `laptop restart karo` (always asks; 1-minute delay;
`shutdown cancel karo`) · `laptop ka volume kam karo` / `pc ka volume 30 percent` · `PC pe gaana pause karo` ·
`computer pe youtube kholo` · `pc pe type karo hello world` · `pc ka status batao` · `PC ka screenshot bhejo`.

The phone's home screen has quick chips for these. Windows is the main target; Linux/macOS use standard tools. Optional
extras make it better: `pip install pycaw psutil pyperclip winotify`.

## 7. Deeper phone control

| Say | |
|---|---|
| `mera phone kahan hai` · `find my phone` | rings at full alarm volume **even on silent**, vibrates and flashes the torch for 30 s. `ringing band karo` stops it |
| `phone ki location batao` | GPS/network location with a Google Maps link (needs Location, "Allow all the time") |
| `call utha lo` · `call kaat do` · `speaker on karo` · `mic mute karo` | call control (needs *Answer calls*) |
| `kaunsa gaana chal raha hai` | now playing from any media app |
| `aaj maine phone kitna chalaya` · `kal ka screen time` · `is hafte ka screen time` | screen time + top apps + unlocks (needs *Usage access*) |
| `storage kitna bacha hai` · `battery health batao` · `phone ki details` | device info |
| `auto rotate band karo` · `screen timeout 2 minute kar do` | system settings (needs *Modify system settings*) |
| `gaana aage karo` / `rewind` | seek in the current track |

## 8. Screen intelligence

`screen pe kya hai` → a short summary · `ye padh ke sunao` → reads the article/message aloud · `iska summary do`.
In agent tasks the planner can now `find_text` (scroll until a label appears) and `read_screen` (read long text) — so
questions like *"is page pe price kya likha hai"* work. Password fields are never read.

## 9. Weather & briefing

`Delhi ka mausam kaisa hai` · `kal barish hogi?` · `weather in Mumbai` · `aaj garmi kitni hai` — free Open-Meteo, no
key. City = the one you say, else `[assistant] city`, else the phone's location.

`briefing do` / `good morning` → greeting, date & time, weather, phone battery, a notification summary, yesterday's
screen time and what's coming up today (routines and reminders).

## 10. Smarter conversation

- Follow-ups: `Priya ko bolo kal milte hain` → `usko call bhi karo` → `wahi message Mummy ko bhi bhejo`.
- When Nixin asks something by voice ("Kitne baje ka alarm lagaun?"), it keeps listening for a few seconds so you can
  just answer (`[voice] follow_up_seconds`).

## 11. Plugins

Drop a `.py` file in `<data dir>/plugins/` to add your own commands — see [PLUGINS.md](PLUGINS.md).
