# Security & privacy

Nixin can tap anything on your phone, so safety is built into both ends — and the **phone has the final say**.

## Threat model
| Threat | Defence |
|---|---|
| Someone on your Wi-Fi connects to the PC | Pairing needs a single-use, 5-minute, 256-bit token from a QR you scan; every later connection must sign a fresh nonce with the phone's Keystore key |
| Someone impersonates your PC | The phone pins the PC certificate's SHA-256 fingerprint from the QR; anything else fails TLS |
| Replay of old traffic | TLS + per-connection nonce; request ids are de-duplicated on the phone |
| A web page talks to the dashboard | Dashboard binds to 127.0.0.1, requires a random per-run token (cookie), and the WebSocket rejects foreign `Origin`s |
| The LLM hallucinates or is prompt-injected by screen text | Fixed tool set; every tool call validated against the current snapshot; screen text marked untrusted; phone-side rules below cannot be changed by the PC or the model |
| Wrong recipient / double send | Contacts are resolved (ambiguity → you choose), external actions need confirmation per policy, WhatsApp workflow verifies the composer text, taps Send once, and reports `uncertain` instead of retrying |
| Runaway agent | Step/time limits, repeat and no-progress detection, cancel from 5 places, durable kill switch |
| Surprise bills | Only listed free candidates are used; local budgets per model; no paid fallback exists |
| Lost/stolen PC data | `nixin.db` holds public keys only; unpair from the dashboard or `nixin unpair`; "Forget this PC" on the phone deletes the Keystore key |

Out of scope: a fully compromised PC (it *is* the brain — unpair it) and physical access to an unlocked phone.

## Phone-side rules (cannot be disabled remotely)
- **Blocked apps**: ~60 banking/UPI/wallet/investing/crypto/password-manager/authenticator packages, system permission & credential UIs, plus any package name containing bank/wallet/authenticator/password/paisa or a `.upi.`/`.pay.`/`.otp.` segment, plus your own additions. Nixin will not open, read, tap, type or screenshot them.
- **Sensitive fields**: password, PIN, OTP, CVV, card-number fields are never read (text not serialized) and never typed into.
- **Sensitive taps**: Send / Pay / Buy / Order / Delete / Transfer / Call / Post / Share … require the PC's confirmation flag.
- **External methods** (call, SMS, WhatsApp) require `meta.confirmed=true`, which the PC sets only after its confirmation gate.
- **Kill switch**: the notification **STOP** persists across restarts; the PC cannot clear it — only **Resume** in the app.
- **Locked phone**: no screen automation; Nixin never tries to unlock.
- **OTP masking** in notifications.
- `allowBackup=false`: pairing data is never restored onto another device.

## Confirmation policy (`assistant.confirm`)
| Source | smart (default) | trusted | always |
|---|---|---|---|
| typed exact command (console/dashboard/phone text) | direct | direct | ask |
| push-to-talk / phone voice | ask | direct | ask |
| AI-interpreted (classifier) or agent-initiated | ask | ask | ask |
| wake word | ask | ask | ask |

Answer on any channel: voice ("haan"/"nahi"), phone dialog or notification buttons, dashboard, console. No answer in 30 s = no.

## What leaves your devices
| Data | Where | Control |
|---|---|---|
| Command text, compact screen text | the LLM provider that serves the call | `privacy.cloud_llm` (off → only router commands work) |
| Voice audio | Groq Whisper | `privacy.cloud_stt` (off → local faster-whisper) |
| Screenshots | vision model | `privacy.cloud_vision` (default **off**) + phone "Allow screenshots" (default **off**) |
| Replies (TTS) | Microsoft edge-tts | use `pyttsx3`/`piper` for offline |

Nothing else: no telemetry, no relay server. Logs: the audit log truncates message bodies; screenshots and audio are never stored.
