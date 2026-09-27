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

## Next
- [ ] Tune WhatsApp selectors for your installed version (ids `entry`/`send` are standard, but WhatsApp experiments with layouts)
- [ ] Notification quick-reply (RemoteInput) so "Rahul ko reply karo …" works without opening WhatsApp
- [ ] Custom "Hey Nixin" wake-word model (openWakeWord Colab) + false-accept measurement
- [ ] Windows lock → pause the link; DPAPI-protected TLS key
- [ ] Per-app "recipes" (known flows cached from successful agent runs to skip LLM calls next time)
- [ ] Hindi (Devanagari) message bodies through the router (currently go to the classifier)
- [ ] Instrumented Android tests on a real device / emulator in CI
- [ ] Multi-phone support
