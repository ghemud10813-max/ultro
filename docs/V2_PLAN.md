# Nixin 2.0 — plan

v1 made Nixin *do things when asked*. v2 makes it **proactive, teachable and two-way**: it reacts to what happens on the phone, learns routines by watching you, bridges files/clipboard/notifications between PC and phone, and controls the PC too.

## Themes

| # | Theme | What you can say / do | How |
|---|---|---|---|
| 1 | **Routines & scenes** | "har raat 11 baje phone silent kar dena", "jab battery 20% se kam ho to bata dena", "good night" → DND + alarm + brightness | Routine engine on the PC: time / interval / phone-event / phrase triggers → commands. Built-in scenes. Created by voice or the dashboard |
| 2 | **Teach mode (skills)** | "Nixin, sikho: chai order" → you do it on the phone → "save karo" → later "chai order chalao" | Phone records your taps/typing as semantic steps; PC replays them with verification (no LLM). Successful agent runs are also saved as skills automatically |
| 3 | **Notification intelligence** | live notification feed on PC, "Rahul ko reply karo: aa raha hoon" (replies through the notification, no UI), "mere unread messages summarize karo", VIP announcements ("Mummy ka message aaya: …") | Opt-in notification mirroring, `notif.reply/dismiss/open`, messaging-style history, LLM summary |
| 4 | **PC ⇄ phone bridge** | share anything on the phone → lands on the PC; drop a file on the dashboard → lands in phone Downloads; "PC ka clipboard phone pe bhejo"; "yeh photo wallpaper laga do" | Chunked file transfer, share target, clipboard, wallpaper |
| 5 | **Control the PC too** | from the phone: "PC lock karo", "laptop ka volume kam karo", "PC ka screenshot bhejo", "computer pe youtube kholo" | PC-control module (lock/sleep/volume/media/open/screenshot/clipboard/type/status) + a PC tab in the app |
| 6 | **Deeper phone control** | "mera phone dhundo" (rings at full volume + flashes, even on silent), "phone kahan hai" (GPS), "call utha lo / kaat do / speaker on", "kaunsa gaana chal raha hai", "aaj maine phone kitna chalaya", "auto rotate band karo", "screen timeout 2 minute" | New native methods: ring, location, call control, now-playing, usage stats, settings, info, vibrate |
| 7 | **Screen intelligence** | "screen pe kya hai?", "yeh article padh ke sunao", "iska summary do" | `ui.text` + summariser; agent tools `read_screen`, `find_text` (auto-scroll) |
| 8 | **Briefings & weather** | "good morning" → time, weather, battery, unread summary, yesterday's screen time; "kal barish hogi?" | Open-Meteo (free, no key) + phone data |
| 9 | **Smarter conversation** | "Rahul ko bol main aa raha" … "usko call bhi karo", "wahi message Priya ko bhi bhejo" | Remembers the last contact / app / message; follow-up listening after voice replies |
| 10 | **Plugins** | drop a `.py` file in the plugins folder to add your own commands | Tiny plugin API |

## Protocol additions (shared/protocol/methods.json)
`device.info`, `device.ring`, `device.location`, `device.setting`, `device.vibrate`, `device.wallpaper`, `clipboard.set`, `clipboard.get`, `file.push`, `notif.reply`, `notif.dismiss`, `notif.open`, `media.now_playing`, `call.control`, `usage.stats`, `ui.text`, `ui.scroll_to`, `rec.start`, `rec.stop`, `nixin.notify`.

New messages: phone → PC `event` names `battery`, `power`, `screen`, `network`, `notification`, `call_incoming`; `share` (text/link from share sheet); `file` (chunked file from share sheet). PC → phone `scenes` (quick-action chips).

## Safety additions
- Routines run with source `routine`: external actions still confirm unless the routine is marked *trusted* in the dashboard.
- `notif.reply` is an external action (confirmation policy applies).
- Teach mode never records password fields or blocked apps; a visible notification shows while recording.
- Location and notification mirroring are off until you enable them on the phone.
- PC shutdown/restart always confirm.

## Build order
1. protocol → 2. phone capabilities & events → 3. PC modules (memory context, PC control, weather/briefing, routines, skills, bridge, notifications, screen, plugins) → 4. router + classifier + agent tools → 5. dashboard v2 → 6. simulator + tests → 7. Android UI (share target, PC tab, inbox, teach indicator, shortcuts) → 8. docs, CI, zip.
