# Roadmap & test plan

## Done (v1.0)
- [x] Shared protocol registry (`shared/protocol/methods.json`) with parity tests on both sides
- [x] Pairing: QR / deep link / paste, pinned TLS, Keystore ECDSA, single-use tokens, unpair
- [x] Phone link: reconnect with backoff, network-change reconnect, heartbeat watchdog, boot auto-start
- [x] Phone policy firewall: kill switch, blocklist, sensitive fields/taps, confirmations, timeouts, dedupe, cancellation
- [x] Native controls: volume, torch, brightness, ringer, DND, global actions, settings panels, media keys
- [x] Apps & intents: list/open (fuzzy), URL, web/YouTube/Play/Maps/Spotify search, navigation, alarms, timers
- [x] People: contacts, calls, SMS, WhatsApp send-once workflow
- [x] Screen: compact serializer, tap/long-press/type/scroll/swipe/key/tap-text/wait, accessibility screenshots
- [x] Notifications reader (in-memory, OTP masked)
- [x] Hinglish/English deterministic router (Devanagari transliteration, time/duration parser, multi-intent)
- [x] Multi-provider LLM gateway: roles, fallbacks, key pools, local free-tier budgets, model probing
- [x] Classifier + LangGraph agent (validate → act → verify), vision `look()` with set-of-marks
- [x] Confirmation gate on console / dashboard / phone / voice
- [x] Memory: nicknames, app aliases, facts, conversation
- [x] Voice on PC: push-to-talk, kill hotkey, Groq Whisper + faster-whisper, edge-tts/pyttsx3/Piper, optional wake word
- [x] Voice on phone: SpeechRecognizer, TTS replies, Quick Settings tile, notification Talk button
- [x] Dashboard: live mirror (click = tap, drag = swipe), timeline, tasks, memory, models, settings, pairing
- [x] CLI, phone simulator, demo mode, ADB power mode templates
- [x] CI: Python tests, APK build + unit tests + lint, APK artifact

## Done (v2.0)
- [x] Routine engine: time / interval / once / phone-event / phrase triggers, built-in scenes, cooldowns, trusted routines
- [x] Voice-created routines and reminders ("har raat 11 baje…", "jab battery 20% se kam ho…", "10 minute baad yaad dilana…")
- [x] Teach mode (accessibility recording → semantic steps → verified replay with agent fallback) + auto-learned agent routes
- [x] Notification quick-reply (RemoteInput), dismiss/open, live mirror, VIP announcements, LLM summaries
- [x] PC ⇄ phone bridge: share target, chunked files both ways, clipboard, wallpaper, inbox
- [x] PC control: lock/sleep/shutdown(confirm)/volume/media/open/search/type/screenshot/status/notifications
- [x] Phone: find-my-phone ring, location, call control, now playing, screen time, device info, system settings, seek
- [x] Screen reading + summaries; agent tools `find_text`, `read_screen`
- [x] Weather (Open-Meteo) + daily briefing; follow-up voice listening; pronoun/"same message" follow-ups
- [x] Plugin API + example plugin; dashboard Automations / Notifications / Files / Phone & PC tabs; phone quick chips & shortcuts

## Device test checklist (do this on your Samsung first)
Run `nixin run`, keep the dashboard open, and tick these off. Anything that fails: note the command, the dashboard timeline and the phone's Activity tab.

1. **Pairing** — scan QR → "Connected". Kill the app from recents → it reconnects. Toggle Wi-Fi → reconnects within seconds. Screen off 10 min → still connected (battery Unrestricted!).
2. **Kill switch** — notification STOP → any command replies "kill switch on" → Resume in app → works again. Reboot → still stopped until Resume.
3. **Native** — volume up/down/set/mute, torch on/off, brightness (after Modify-settings permission), silent/vibrate, DND, screenshot, lock screen, back/home/recents.
4. **Apps** — "WhatsApp kholo", "camera kholo", "google pay kholo" (must be refused), YouTube search + play.
5. **Alarm/timer** — "kal subah 6 baje ka alarm", "5 minute ka timer" (check Clock app).
6. **Notifications** — after notification access: "meri latest notification padh ke bata"; OTP SMS shows as ••••••.
7. **WhatsApp** (use a test contact!) — typed: sends directly; voice: asks first; "nahi" → nothing sent; ambiguous name → you choose; number not on WhatsApp → clear error.
8. **Agent** — "settings mein dark mode on karo", "Instagram pe latest post like karo", "YouTube pe history kholo". Watch the timeline; try Ctrl+Alt+K mid-task.
9. **Safety** — open a banking app manually and ask "screen pe kya hai" → refused; focus a password field and ask to type → refused.
10. **Mirror** — enable Allow screenshots → dashboard mirror updates ~1 fps, click taps.

### 2.0 checklist
11. **Routines** — `har raat 11 baje phone silent kar dena` (then edit the time on the dashboard to 2 minutes from now and wait); `jab charger lagaun to bata dena` → plug in; `good night`.
12. **Reminders** — `2 minute baad yaad dilana ki chai` → phone notification + spoken reminder.
13. **Teach mode** — `sikho: mummy chat` → open WhatsApp, tap Mummy → Save in the notification → go home → `mummy chat chalao`.
14. **Notifications** — enable *Mirror notifications*; send yourself a WhatsApp from another phone → appears on the dashboard; reply from the dashboard; `X ko reply karo: ok`; add yourself as VIP → spoken.
15. **Bridge** — share a photo to *Send to PC* → `~/Nixin Inbox`; drop a PDF on the dashboard → phone Downloads/Nixin; `ye photo wallpaper laga do`.
16. **PC control** — from the phone: `PC lock karo`, `PC ka screenshot bhejo`, `laptop ka volume kam karo`.
17. **Find my phone** — put the phone on silent, `mera phone kahan hai` → rings at full volume; Stop from the notification; `phone ki location batao` (Location: Allow all the time).
18. **Calls** — have someone call you: `call utha lo`, `speaker on karo`, `call kaat do` (Answer-calls permission).
19. **Screen time / info** — grant Usage access → `aaj maine phone kitna chalaya`; `storage kitna bacha hai`.
20. **Screen reading** — open an article → `ye padh ke sunao`, `iska summary do`.

## Next
- [ ] Tune WhatsApp selectors for your installed version (ids `entry`/`send` are standard, but WhatsApp experiments with layouts)
- [ ] Custom "Hey Nixin" wake-word model (openWakeWord Colab) + false-accept measurement
- [ ] Windows lock → pause the link; DPAPI-protected TLS key
- [ ] Parameterised skills with more than one argument ("pizza order: margherita, large")
- [ ] Location-based routines (geofences) and calendar-driven briefings
- [ ] Hindi (Devanagari) message bodies through the router (currently go to the classifier)
- [ ] Instrumented Android tests on a real device / emulator in CI
- [ ] Multi-phone support
