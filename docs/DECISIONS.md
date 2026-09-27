# Design decisions — what changed from the ULTRON plan, and why

Your raw idea (translated): *"Groq with qwen 3.8 27b, gpt-oss-120b and gpt-oss-20b, multiple APIs, host a service on Render or Cloudflare for the connection, agents built from these models with LangGraph, full control of the phone, everything free."* The ULTRON planning docs (kept in `docs/archive/ultron-plan/`) turned that into a very thorough, very strict spec. Nixin keeps the core of both and deliberately simplifies where the complexity didn't buy safety or reliability for a one-person project.

## Kept from your idea
- **Three Groq models with clear roles** — gpt-oss-20b (fast understanding), gpt-oss-120b (the step-by-step phone agent), qwen (verifier + backup).
- **Multiple APIs** — Groq, Cerebras, Gemini, OpenRouter, Cloudflare, Ollama behind one gateway; several keys per provider can be pooled.
- **LangGraph** for the agent loop.
- **Full control** — native controls, any app via accessibility, screenshots, plus optional ADB power mode.
- **100% free.**

## Changed from your idea
| Idea | Nixin | Why |
|---|---|---|
| Host a connection service on Render / Cloudflare | **No server.** Phone connects straight to the PC on Wi-Fi; Tailscale for outside home | Render's free tier sleeps and cold-starts (~50 s), adds latency to every tap, and puts a public endpoint between you and your phone. Tailscale is free, encrypted, needs no open ports |
| Call all three models on tasks | **Router → one fast call → agent only when needed** | Groq free tier is ~8k tokens/minute per model. Every avoided call keeps Nixin instant |
| qwen 3.8 27b "for 2–3 tasks" | Verifier (and vision if multimodal), with automatic fallback to `qwen3-32b` | I could not verify that `qwen/qwen3.8-27b` exists on Groq; the gateway checks `/models` at startup and skips it if not |
| "Multiple API keys" to get more quota | Supported for keys you legitimately own | Creating accounts to evade limits breaks provider terms; the gateway already spreads load across providers |

## Kept from the ULTRON docs
PC = brain / phone = hands; phone-initiated WebSocket; deterministic router first; bounded agent with one action per step; strict tool validation; phone-side policy firewall; finance/credential blocklist; sensitive-field protection; durable kill switch that only the phone can clear; no auto-retry of uncertain sends; pairing with QR + pinned certificate + Keystore key; SQLite audit; fixed ADB templates only; honest known limitations.

## Simplified from the ULTRON docs (and why that's OK)
| ULTRON plan | Nixin | Reason |
|---|---|---|
| Exact per-direction sequence numbers, clock-skew negotiation, monotonic deadline conversion | TLS ordering + per-connection nonce + request-id dedupe + relative `timeoutMs` | TLS already guarantees order/integrity within a session; relative timeouts avoid clock sync entirely |
| Immutable authorization scopes with content SHA-256 digests on every action | PC confirmation gate + `meta.confirmed` flag + phone-side sensitive-tap detection | Same protection against the model inventing a send, with far less protocol surface; the ULTRON doc itself notes a compromised PC is out of scope |
| Four independent cloud data-class toggles + image-redaction proofs | Three privacy switches (LLM text, STT audio, vision) + phone "Allow screenshots" (default off) | Covers every real data flow; screenshots stay opt-in on both ends |
| Pinned app signer allowlist, generic automation default-deny | Default-allow with a strong blocklist (list + name heuristics) | Default-deny would make "open any app and do X" impossible — the core of "full control" |
| Manual contact enrollment with verified E.164 numbers | Read contacts on the phone; ambiguous names → you pick; nicknames in memory | Far less setup; ambiguity still never guessed |
| MediaProjection for screenshots | AccessibilityService `takeScreenshot` (Android 11+) | No consent dialog every session; secure windows still blocked by Android |
| WhatsApp: search UI + title check | Click-to-chat link with the number + composer verification + single Send tap | Opens the exact chat by number (no fuzzy search), much fewer brittle selectors |
| Windows-lock suspends the session; DPAPI for the key | Not implemented | Low value for a personal PC; noted in ROADMAP |
| Piper-only TTS | edge-tts (natural Indian voices, free) → pyttsx3/Piper offline | Much better Hinglish pronunciation; offline fallback retained |
| minSdk 31 | minSdk 30 | Accessibility screenshots + IME actions need 30; widens device support |

## Other choices
- **FastAPI + uvicorn** for both the phone link (TLS) and the localhost dashboard, one asyncio loop.
- **No provider SDKs** — a ~200-line OpenAI-compatible client gives full control over errors, headers and fallbacks.
- **LangGraph without checkpoints** — task steps are persisted to SQLite for inspection; old actions are never replayed.
- **Compact screen text instead of screenshots** as the default observation — 10–50× fewer tokens, more private, works offline from vision models.
- **Kotlin without DI or serialization plugins** — a small service locator and `JsonObject` helpers keep the build simple.
- **Phone simulator** in Python so the whole system can be developed and tested without a device.
