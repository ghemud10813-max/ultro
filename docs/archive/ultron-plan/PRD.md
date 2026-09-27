# ULTRON Product Requirements Document

**Status:** Build-ready plan  
**Primary PC:** Windows 11  
**Primary phone:** Samsung, Android 12  
**MVP:** System controls and one-to-one WhatsApp text messages

## 1. Product vision

ULTRON is a local-first personal assistant whose Windows PC performs speech processing and task orchestration while an explicitly paired Android phone performs authorized actions through native Android APIs, intents, AccessibilityService, and optional on-demand screen capture.

The realistic promise is **reliable automation of supported actions**, not unrestricted control of every Android screen.

## 2. Problem

Phone automation is fragmented: native assistants support selected commands, accessibility automation is brittle, and general LLM agents can be slow, expensive, or unsafe. ULTRON combines:

- a fast deterministic path for known commands;
- a bounded agent path for multi-step tasks;
- an Android-side policy firewall;
- local speech fallbacks and zero-cost cloud tiers;
- inspectable actions, failures, and usage.

## 3. Product principles

1. **Local control plane:** no hosted relay is required on the home LAN.
2. **Deterministic before agentic:** known operations do not consume LLM quota.
3. **Phone enforces policy:** neither the PC nor a model can override blocked contexts.
4. **One action at a time:** observe, act, verify, then continue.
5. **No silent uncertainty:** uncertain external actions are not automatically retried.
6. **Zero mandatory spend:** no paid fallback, billing method, or automatic upgrade is enabled; third-party free tiers are optional and may change.
7. **Graceful degradation:** native commands remain available when cloud APIs fail.
8. **Explainable operation:** every task exposes status, action history, and a concise reason for failure.

## 4. Users and environment

### Primary user

A technical student using one Windows 11 PC and one personally owned Samsung Android 12 phone on the same trusted Wi-Fi network.

### Required runtime conditions

- Phone is unlocked before a UI automation task begins.
- Windows is unlocked and the interactive ULTRON user session is active; Windows lock suspends the trusted phone session and expires pending authorization.
- ULTRON AccessibilityService is enabled.
- ULTRON's Android foreground service is running.
- PC and phone are on the same LAN for the initial releases.
- Each cloud data class is separately disabled by default and requires its own informed opt-in: microphone audio, command text, compact UI-tree text, and redacted images. Enabling cloud mode alone enables none of them.

## 5. Goals

- Execute supported system controls from typed or spoken Hinglish/English commands.
- Send a one-to-one WhatsApp text message to an unambiguous contact.
- Keep normal LAN operation independent of Render, Cloudflare Tunnel, or another relay.
- Use free services without assuming that their limits or model catalogs are permanent.
- Recover cleanly from app changes, disconnections, revoked permissions, and rate limits.
- Make the architecture understandable, inspectable, and testable.

## 6. Non-goals

- iOS support.
- Play Store distribution.
- Multiple phones or multiple users.
- Bypassing the lock screen, Android permission dialogs, or secure windows.
- Financial, banking, UPI, OTP, password, or credential workflows.
- Arbitrary shell access from an LLM.
- Guaranteed automation of every Android app.
- Fully offline general-purpose planning on hardware that cannot run a local LLM.
- A public internet endpoint in the initial releases.

## 7. Operating modes

### Local-only

- Typed input or local speech recognition.
- Deterministic commands and predefined workflows only.
- Piper TTS.
- No command, UI tree, screenshot, or audio leaves the LAN.
- Unsupported open-ended requests fail honestly.

### Cloud-assisted

Cloud-assisted is an availability mode, not blanket consent. Four independent, default-off controls govern export:

1. **Cloud audio:** permits only the activated utterance to an STT provider.
2. **Cloud command text:** permits the normalized command to a model. Without it, message bodies and command text are represented to models only by opaque local content references and digests.
3. **Cloud UI tree:** permits a minimized tree after unrelated chat/history text and sensitive content are redacted.
4. **Cloud image:** requires both phone image export and PC cloud-image forwarding; forwarding fails closed whenever redaction coverage is uncertain.

- A provider role remains disabled until its startup availability and required text/tool/vision capability probe passes.
- Hard local request/token budgets prevent accidental paid usage.
- If every eligible free provider is unavailable or the needed data-class consent is off, ULTRON degrades to an eligible local path or fails honestly.

## 8. Trust and safety model

Pairing is persistent; authorization sessions are temporary.

- Initial pairing uses a short-lived QR token and pinned PC certificate.
- The phone stores its private key in Android Keystore.
- Every connection performs a new challenge-response handshake.
- A trusted session starts after a successful connection and expires on disconnect, PC restart, Windows lock, unpair, certificate revocation, or kill switch.
- The confirmation preference is configurable. In trusted mode, an unambiguous typed or push-to-talk command itself authorizes exactly the requested send; the user may enable an additional per-action confirmation. If calls, share, or delete are later implemented, they always require a separate confirmation regardless of preference. Finance remains blocked.
- PC ingress creates an immutable authorization scope from the original command before any model runs; external actions carry that scope, target, and content digest to the phone.
- An external side effect is allowed only when explicitly requested in that scope. The agent may not infer a send, call, share, or delete action from an unrelated goal.
- Unattended wake-word activation can never create an external-side-effect scope; messaging and other external effects require typed or push-to-talk input. Wake word stays optional and off until a measured false-accept/false-reject gate is agreed.
- Ambiguous recipients or content trigger clarification rather than guessing.
- Banking, payment, UPI, password-manager, authenticator, OTP, and credential contexts are always blocked.
- Generic UI automation is default-deny outside an explicit package plus pinned signer allowlist. The phone rechecks the current window/node package and signer immediately before each observation or action and blocks suspicious package transitions.
- Permission-controller, credential/biometric, IME/keyboard, overlay, and generic System UI windows are never observed or automated. A later notification adapter must be source-aware and redact OTP-like content.
- External message bodies are supplied to models as opaque local content references unless command-text export is explicitly enabled. Unrelated chats/history are removed before any tree/cloud export, and uncertain screenshot redaction blocks forwarding.
- Android-controlled permission and MediaProjection prompts still require physical interaction.
- The persistent phone notification and a Windows hotkey provide kill switches. A kill switch durably stops the phone, ends the session, and clears queues; only a physical action in the phone UI may clear the stopped state, after which a fresh session is required.
- A fully compromised paired PC is outside this threat boundary; unpairing and PC key protection are required mitigations.

## 9. MVP capability matrix

| Capability | Mechanism | MVP | Notes |
|---|---|---:|---|
| Volume up/down/set | `AudioManager` | Yes | Native and deterministic |
| Torch on/off | `CameraManager` | Yes | Requires camera permission on relevant devices |
| Open app | Launch intent | Yes | Installed-app allowlist |
| Back/home/recents | Accessibility global action | Yes | Home may end the current workflow |
| Create alarm | `ACTION_SET_ALARM` intent | Yes | Represents the next occurrence of the requested local clock time, not an arbitrary date; `tomorrow` is accepted only when it agrees with next-occurrence semantics, otherwise clarify/fail |
| Read compact screen tree | AccessibilityService | Yes | Filters sensitive and irrelevant nodes |
| Tap by element ID | AccessibilityService | Yes | Snapshot-scoped IDs; coordinates are fallback only |
| Type into editable field | AccessibilityService | Yes | Blocked in sensitive fields/packages |
| Scroll | AccessibilityService gesture/action | Yes | Bounded distance and direction |
| WhatsApp one-to-one text | Phone-side known workflow | Yes | No groups, media, calls, or voice notes in MVP |
| Screenshot | MediaProjection | Vision phase after agent | On-demand; phone-side image-export toggle and OS consent required |
| Notification reading | Notification access | Later | Dedicated source-aware adapter; generic System UI observation stays blocked |
| Wi-Fi/mobile data/airplane mode | Settings panel or ADB | No direct MVP toggle | Android restrictions apply |
| Install APK or shell command | Wireless ADB power mode | Later | Opt-in and allowlisted templates only |
| Locked-screen automation | None | No | User unlock required |

## 10. User stories and acceptance

### Foundation

- As the user, I can pair the phone by scanning a QR code so unknown LAN devices cannot issue actions.
- As the user, I can type `volume badha do` and observe the media volume increase.
- As the user, I can type `WhatsApp kholo` and see WhatsApp open.
- As the user, I can stop all queued actions from the persistent phone notification.

### Voice and deterministic router

- As the user, I can press a push-to-talk hotkey and issue Hinglish or English commands.
- As the user, I receive an offline spoken success or failure reply.
- As the user, known commands work even if every LLM provider is unavailable.

### Agent and WhatsApp

- As the user, I can manually enroll Rahul to a stable local `contactId` using a user-entered and verified E.164 number (or another deterministic workflow identifier) plus expected display name.
- As the user, I can say `WhatsApp pe Rahul ko bol main 10 min late hoon` and have ULTRON resolve that enrollment, verify recipient identity before and after Send, enter the exact text, send it once, and report `send accepted` when the outgoing message is visible locally.
- As the user, I am asked to clarify when enrollment, speech confidence, recipient, content, or time is ambiguous.
- As the user, I receive a truthful `uncertain` result if local send acceptance cannot be verified; ULTRON does not claim delivery and does not resend automatically.

### Reliability and privacy

- As the user, I can inspect a redacted action log without exposing passwords or OTPs.
- As the user, I can independently disable cloud audio, command-text, UI-tree, phone image export, and PC cloud-image forwarding.
- As the user, reconnecting after Wi-Fi loss creates a fresh session and reconciles an uncertain action by `actionId` without resubmitting it.
- As the user, locking Windows immediately suspends the session and expires pending authorization.

## 11. Functional requirements

### PC

- Provide CLI text input before voice features.
- Bind the WebSocket server to the selected private-network interface only.
- Route known commands with deterministic patterns and typed entity extraction.
- Run a bounded LangGraph workflow only for unresolved multi-step commands.
- Store pairings, task state, usage, preferences, and redacted audit records in SQLite.
- Store provider keys outside source control; prefer Windows Credential Manager.
- Track requests and tokens per provider/model and enforce configurable daily ceilings.
- Speak replies through Piper by default.

### Android

- Maintain an authenticated WebSocket from a visible foreground service.
- Reconnect with exponential backoff and stop retrying when the user disables the service or durable stopped state is set.
- Validate protocol version, session, exact next sequence, schema, package/signer/category policy, current window/node identity, deadline, data class, and capability immediately before execution.
- Cache action state/results to prevent duplicate external side effects and answer read-only status reconciliation after reconnect.
- Serialize only useful visible UI nodes with stable snapshot-scoped IDs.
- Never expose sensitive-field text.
- Report explicit capability and permission state instead of pretending an action succeeded.

### WhatsApp workflow

- Support only the official installed WhatsApp package whose signing certificate matches the pinned signer allowlist and whose version is in the tested range.
- Enroll contacts manually to a stable local `contactId` with a user-entered/verified E.164 number or other deterministic workflow identifier and expected display name; visible title alone is insufficient.
- An ordinary WhatsApp request authorizes only `workflow.whatsapp.send_text`; all app opening, navigation, search, typing, and Send activation are internal to the phone workflow.
- Prefer element IDs/text over screen coordinates and recheck package, signer, recipient identifier, and expected display name immediately before Send.
- Enter exactly the requested message; the model may not receive or embellish it unless command-text export is enabled.
- Capture structured before evidence and after evidence. `succeeded` means Send was accepted and the exact outgoing text is visible locally; it does not mean network delivery or receipt.
- Return `uncertain` rather than retrying if local send acceptance is unclear.

### Alarm semantics

- `ACTION_SET_ALARM` schedules the next occurrence of a local hour/minute; it does not encode an arbitrary calendar date.
- A request saying `tomorrow` is accepted only when the requested time's natural next occurrence is tomorrow. If that time is still later today, ULTRON must clarify or fail honestly rather than claim a dated alarm.

## 12. Delivery phases

| Phase | Scope | Demo exit criterion |
|---|---|---|
| 0. Contract | Capability matrix, protocol fixtures, policy fixtures | Schemas validate and blocked-context tests pass |
| 1. Foundation | Pairing, WSS, foreground service, typed native actions | Typed PC command controls Samsung Android 12 |
| 2. Voice | Push-to-talk, STT, deterministic router, Piper | Five Hinglish/English command families work without an LLM |
| 3. WhatsApp workflow | Compact UI tree, contact resolution, send-once workflow | 18/20 controlled one-to-one message trials succeed with no duplicates |
| 4. Bounded agent | LangGraph, configured Navigator, optional Strategist escalation | Multi-step tasks terminate correctly and remain within limits |
| 5. Vision and reliability | On-demand projection, configured visual verifier, provider adapters, memory | Tree-failure cases recover when image export is enabled |
| 6. Extras | Wake word, dashboard, Tailscale, ADB power mode | Each extra can be independently enabled and disabled |

## 13. Success metrics

| Metric | Target |
|---|---:|
| Parsed-command to native-action result on LAN | p50 under 500 ms; p95 under 1.5 s |
| Voice command to native-action result | p50 under 3 s on normal network |
| Deterministic command accuracy on agreed 50-command Hinglish/English set | At least 95% |
| WhatsApp controlled-test local send acceptance | At least 90% over 20 runs on the pinned signer/supported version; no delivery claim |
| Duplicate messages during retry/disconnect/reconciliation tests | 0 |
| Package/signer/category/window/overlay/IME and sensitive-field policy tests | 100% blocked |
| Privacy data-class tests | No cloud export occurs without the matching independent consent; uncertain image redaction sends 0 bytes |
| Kill-switch response | No new action starts after 1 s; stopped state survives restart until physical phone resume |
| Windows lock response | Session suspended and pending authorization expired within 1 s of lock event |
| Action reconciliation | 100% of accepted actions reach a terminal result or an explicit retained `unknown_action` finding without resubmission |
| Agent hard termination | At most 12 actions or 120 s per task |
| Audit coverage | Every accepted action has a terminal status |
| Paid API charges | ₹0 / $0 |

Success metrics are release gates for the tested phone and app versions, not universal Android guarantees.

## 14. Known limitations

- Phone must normally be unlocked.
- Samsung battery management can stop background connections until the user exempts the app.
- Accessibility trees may omit custom canvas, games, WebViews, or some Compose content.
- `FLAG_SECURE` screens can block screenshots.
- MediaProjection requires Android-controlled consent and can end unexpectedly.
- WhatsApp UI updates, language changes, or experiments may break selectors.
- Free model availability, quotas, and tool/vision support can change without notice.
- Hinglish names and noisy audio can remain ambiguous.
- Wake-word false activations cannot be eliminated completely.
- LAN-only mode stops working when the PC sleeps or changes network.

## 15. Definition of done

A phase is complete only when its demo works on the target Samsung Android 12 phone, automated contract/policy tests pass, logs show no secret leakage, failure behavior is demonstrated, and setup instructions reproduce the result on Windows 11.