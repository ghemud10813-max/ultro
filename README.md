# Nixin

**Nixin is a voice-controlled AI agent that runs on your PC and operates your Android phone** — it opens apps, taps, types, scrolls, reads the screen and finishes multi-step tasks for you, in Hinglish or English, using only free AI tiers.

> "Nixin, WhatsApp pe Rahul ko bol main 10 min late hoon" → Nixin finds Rahul in your contacts, asks "bhejun?", opens the chat, sends it once, and confirms.

```
 You ──voice/text──►  PC BRAIN (Python)                        ANDROID PHONE (Kotlin)
                      ┌───────────────────────────────┐        ┌──────────────────────────────┐
  Ctrl+Alt+N  ──────► │ STT (Groq Whisper / local)    │        │ Foreground service + STOP     │
  dashboard   ──────► │ Hinglish router  (no LLM, 1ms)│  WSS   │ Policy firewall (blocklist,   │
  phone mic   ──────► │ Classifier  gpt-oss-20b       │◄──────►│  confirmations, kill switch)  │
                      │ Agent (LangGraph) gpt-oss-120b│ pinned │ AccessibilityService: read /  │
                      │ Verifier  qwen                │  TLS   │  tap / type / scroll / shot   │
                      │ Memory · audit · dashboard    │        │ Native: volume, torch, alarm, │
  ◄──── speaks ────── │ TTS (edge-tts / offline)      │        │  calls, SMS, WhatsApp, notifs │
                      └───────────────────────────────┘        └──────────────────────────────┘
```

## What it can do

| Kind | Examples | How |
|---|---|---|
| Instant controls (no AI call) | `volume badha do`, `torch on karo`, `brightness 40`, `phone silent kar do`, `DND on`, `screenshot lo`, `peeche jao` | deterministic Hinglish router → native Android APIs |
| Apps & intents | `Instagram kholo`, `youtube pe lofi chalao`, `india gate ka rasta dikhao`, `kal subah 6 baje ka alarm`, `5 minute ka timer` | router → intents |
| People | `Rahul ko call karo`, `WhatsApp pe Mummy ko bol main aa raha hoon`, `Priya ko sms bhejo ki …` | contacts lookup → confirmation → verified send-once workflow |
| Reading | `meri latest notification padh ke bata`, `battery kitni hai` | notification listener (OTPs masked) / device status |
| Anything else | `Instagram pe latest post like karo`, `settings mein dark mode on karo` | LangGraph agent: observe screen → one action → verify → repeat |
| Memory | `yaad rakhna ki meri car ka number DL3C…`, "bhai = Rohan Sharma" | SQLite on your PC |

Plus: a local **web dashboard** with a live phone mirror you can click to tap, a live agent timeline, confirmations, task history, memory editor, model usage and settings; a **phone app** with chat + voice, a Quick-Settings tile and a notification **STOP** button; and a **phone simulator** so you can try everything without a phone.

## Quick start

**PC (Windows 11, Python 3.11+):**
```powershell
cd brain
powershell -ExecutionPolicy Bypass -File ..\scripts\setup-windows.ps1   # uv, deps, .env, firewall rule
notepad .env                                                            # paste your free GROQ_API_KEY
.venv\Scripts\nixin demo      # try it with a simulated phone first
.venv\Scripts\nixin run       # the real thing: shows a pairing QR + opens the dashboard
```

**Phone (Android 11+):** install the APK (download `nixin-debug-apk` from the GitHub Actions run, or `scripts\build-apk.ps1`), open **Nixin → Setup**, scan the QR, then enable Accessibility and set Battery to *Unrestricted*.

Full guide: **[docs/SETUP.md](docs/SETUP.md)**.

## Repository

```
brain/      PC brain — Python package `nixin` (FastAPI, LangGraph, httpx, rich)
android/    Phone app — Kotlin + Jetpack Compose (package com.letvler.nixin)
shared/     protocol/methods.json — the single contract both sides are tested against
docs/       SETUP · ARCHITECTURE · PROTOCOL · AGENT · SECURITY · DECISIONS · ROADMAP
scripts/    Windows helper scripts
.github/    CI: Python tests + APK build/lint, APK uploaded as an artifact
```

## Design in one paragraph

Cheap paths first: a deterministic router handles everyday commands in ~1 ms with zero API calls; a fast model (`gpt-oss-20b`) handles free-form commands in one call; only real multi-step UI work reaches the LangGraph agent (`gpt-oss-120b`), which sees a compact text version of the screen, takes **one** validated action per step and gets its "done" double-checked by a verifier (`qwen`). Every model role has an ordered fallback chain across Groq, Cerebras, Gemini and OpenRouter free tiers, with local rate budgets so Nixin waits or falls back *before* hitting a 429 — and can never use a paid model. Safety is enforced on the **phone**: banking/UPI/password apps are unreachable, password/OTP fields are never read or typed, anything that sends/pays/calls needs confirmation, and the notification STOP button is a durable kill switch. Details: [docs/DECISIONS.md](docs/DECISIONS.md).

## Status

- PC brain: complete, 170+ automated tests (router corpus, TLS pairing, LLM fallback, agent loops, dashboard, end-to-end with the simulated phone).
- Android app: complete; service/logic layer compiled and unit-tested; the full APK is built by CI. It still needs real-device testing on your phone — see [docs/ROADMAP.md](docs/ROADMAP.md) for the device test checklist.

The original ULTRON planning documents are kept in [docs/archive/ultron-plan](docs/archive/ultron-plan).
