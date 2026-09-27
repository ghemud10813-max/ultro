# ULTRON Risk Register

Ratings use **Low / Medium / High / Critical**. `Critical` is reserved for impact that could expose financial, credential, or device-wide control. The owner is the component responsible for the mitigation.

| ID | Risk | Likelihood | Impact | Detection / trigger | Mitigation | Owner |
|---|---|---|---|---|---|---|
| R-01 | Samsung kills the WebSocket foreground service | High | High | Missed heartbeats; process restart; device test | Visible foreground service, reconnect backoff, boot recovery option, Samsung battery-optimization setup, connection health UI | Android transport |
| R-02 | Accessibility permission is revoked or service stops | Medium | High | Capability report changes; action error | Check before every UI task, persistent status, deep link to Accessibility settings, fail without retrying gestures | Android accessibility |
| R-03 | WhatsApp UI/version changes break selectors | High | High | Element not found; identity verification fails; app version changes | Phone-side versioned workflow, semantic selectors, golden UI fixtures, tested-version matrix, fail closed | WhatsApp workflow |
| R-04 | Wrong contact receives a message | Medium | High | Multiple matches; chat title mismatch | Exact nickname mapping, normalize phone/contact identity, verify chat title before typing and before send, ask for clarification on ambiguity | Workflow + policy |
| R-05 | Message is sent twice after timeout/reconnect | Medium | High | Duplicate `actionId`; uncertain transport result | Durable action dedupe cache, cached results, no automatic retry after uncertain external side effect, verify visible outgoing text | Android executor |
| R-06 | Agent loops or repeats ineffective actions | Medium | Medium | Same screen hash/action repeats; elapsed limit | Max 12 actions/120 seconds, no-progress counter, repeated-action guard, terminal failure | Agent graph |
| R-07 | UI text prompt-injects the model | Medium | High | Screen contains model-directed instructions | Treat observations as untrusted data, delimit them, never allow UI text to change policy/tools, validate every action on PC and phone | Agent + phone policy |
| R-08 | Model emits malformed or unsafe tool arguments | Medium | High | JSON/schema validation error | Strict schemas, reject unknown fields, typed enums, package allowlist, bounded text/coordinates, no direct shell tool | Agent validation |
| R-09 | Cloud screenshot leaks private information | Medium | High | Vision fallback requested | Separate opt-in, blocked-package check, sensitive-node masking, crop/downscale, no persistence, provider allowlist, local-only default | Privacy pipeline |
| R-10 | Compact UI tree includes passwords, OTPs, or private text | Medium | High | Sensitive node flags; blocked package | Redact sensitive fields, package/category blocklist, minimize text, test leak fixtures, never log raw trees by default | Android serializer |
| R-11 | Free model is removed, renamed, or rate-limited | High | Medium | Provider errors/catalog mismatch/429 | Capability registry, configurable aliases, circuit breaker, budget counters, local-only degradation, no assumed permanent fallback | Provider gateway |
| R-12 | Free-tier use unexpectedly becomes billable | Low | High | Billing method required or quota policy changes | Do not add billing method, explicit zero-cost provider allowlist, hard local budgets, never auto-upgrade | Provider gateway |
| R-13 | Groq STT is unavailable or mishears Hinglish names | Medium | Medium | Low confidence; provider failure | Local faster-whisper fallback, contact lexicon, clarification for ambiguous entities, typed-input fallback | Speech pipeline |
| R-14 | CPU-only local STT is too slow on Windows | Medium | Medium | Measured real-time factor above target | Use quantized small/medium model, VAD, short utterances, optional NVIDIA acceleration, document hardware profile | Speech pipeline |
| R-15 | Custom `Ultron` wake word is unreliable | High | Medium | False accepts/rejects in test set | Push-to-talk MVP, train/evaluate wake-word model later, audible activation cue, easy disable switch | Voice input |
| R-16 | MediaProjection cannot start silently | High | Medium | Android consent required/session ended | Treat projection as optional on-demand capability, show status, use UI tree first, never claim persistent capture | Android projection |
| R-17 | Secure/custom UI provides no usable tree or image | Medium | Medium | Empty tree, blank image, `FLAG_SECURE` | Return unsupported, do not use blind coordinate guessing, document app limitation | Android observation |
| R-18 | Phone is locked during a task | Medium | Medium | Keyguard/lock-state report | Require unlocked phone, pause/fail task, never attempt unlock or credential entry | Android policy |
| R-19 | LAN attacker attempts connection or replay | Low | High | Invalid token/signature/sequence; certificate mismatch | Pinned WSS, short-lived single-use pairing token, Keystore device key, challenge-response, session sequence numbers, private firewall rule | Security/transport |
| R-20 | PC identity/certificate is lost or copied | Low | High | Pin mismatch or duplicate identity | Protect key with Windows DPAPI, provide explicit unpair/re-pair flow, certificate rotation requires authenticated rotation or re-pairing | PC security |
| R-21 | Pairing token is photographed or reused | Low | Medium | Used/expired token | 256-bit random token, two-minute expiry, one use, invalidate after first successful pair | Pairing |
| R-22 | No-per-action-confirmation causes unintended side effect | Medium | High | False wake/STT or misunderstood command | Trusted session expires on disconnect/restart, external side effects require typed/push-to-talk input, immutable target/content authorization, clarification on ambiguity, kill switch, hard blocked categories | Product policy |
| R-23 | Kill switch arrives after an action has started | Low | High | Cancellation race in logs | Phone-side atomic stopped flag checked before every action, cancel queue immediately, best-effort cancellation for in-flight gestures, visible stopped state | Android executor |
| R-24 | Accessibility is used inside banking/payment/credential apps | Low | Critical | Foreground package/category change | Hard package/category blocklist on phone, stop task on package transition, sensitive-field block, tests cannot be disabled by model/config profile | Android policy |
| R-25 | Wireless ADB enables excessive control | Medium | Critical | Power mode enabled; unexpected template request | Separate opt-in mode, visible indicator, fixed command templates, device allowlist, no arbitrary shell, independent audit and kill switch | ADB executor |
| R-26 | Windows Firewall blocks phone connection | Medium | Medium | Connection timeout on LAN | Private-network-only firewall setup, connectivity diagnostic, QR includes reachable interface address, avoid public profile binding | PC transport |
| R-27 | Dynamic PC IP invalidates endpoint | Medium | Low | Reconnect to stale address | QR re-pair/update flow, optional mDNS discovery, stable DHCP lease guidance | Discovery |
| R-28 | PC sleeps during a task | Medium | Medium | WebSocket disconnect; task interrupted | Detect power state, optional temporary sleep inhibition only during active task, terminal `uncertain` for side effects | PC runtime |
| R-29 | SQLite logs grow or retain sensitive metadata | Medium | Medium | Size/retention audit | Redaction, 30-day default retention, size cap, user purge control, no audio/image retention | Persistence |
| R-30 | Provider logs data under its own policy | Medium | High | Cloud-assisted mode active | Explicit one-time opt-in, provider disclosure, data minimization, local-only mode, no sensitive contexts to cloud | Privacy/product |
| R-31 | Protocol versions drift between PC and APK | Medium | Medium | Negotiation failure/schema mismatch | Version negotiation, shared JSON schemas/golden fixtures, compatibility matrix, fail clearly rather than guessing | Shared protocol |
| R-32 | Duplicate or reordered WebSocket messages | Medium | High | Repeated action ID or sequence gap | Monotonic sequence validation, per-session replay window, action-id result cache, reconnect handshake | Transport |
| R-33 | Generic coordinates hit the wrong control after layout change | Medium | High | Snapshot hash/layout changed | Prefer element IDs, require matching snapshot ID, reject stale snapshot, coordinate fallback only in allowed packages and current bounds | UI executor |
| R-34 | Android/OEM APIs cannot toggle a requested setting | High | Low | Capability unavailable | Capability matrix, use settings-panel intents where possible, reserve allowlisted ADB for power mode, report unsupported honestly | Capability layer |
| R-35 | WhatsApp or provider terms change | Medium | Medium | Terms/app policy update | Personal sideloaded scope, avoid scraping or bulk messaging, no spam/broadcasting, review terms before distribution | Product owner |
| R-36 | Another person uses an unlocked PC or a session remains active after Windows locks | Medium | High | Windows lock/session-change event; unexpected local command | Restrict local IPC/CLI to the signed-in user, expire phone session on Windows lock, require fresh authentication after unlock | PC security |
| R-37 | Android backup exposes pairing or settings | Low | High | Backup/restore test or manifest review | Disable backup for security state, keep private keys non-exportable in Keystore, require re-pair after restore | Android security |
| R-38 | Compromised dependency, model, or voice artifact | Low | High | Hash/signature mismatch, dependency audit | Lock dependencies, verify trusted-source hashes/signatures, record provenance, review updates before adoption | Build/security |
| R-39 | Spoofed or re-signed package impersonates an allowed app | Low | Critical | Package signer mismatch | Pin official signer digest, check package and signer at capability discovery and immediately before observation/action | Android policy |
| R-40 | Overlay, IME, permission controller, or biometric UI captures or redirects input | Medium | Critical | Window/package/type changes or overlay detection | Default-deny these contexts, recheck current window/node identity before execution, stop on suspicious transitions | Android policy |
| R-41 | Certificate expires or rotation breaks trust | Medium | Medium | Expiry warning/pin mismatch | Warn before expiry; perform authenticated rotation with old key or require explicit unpair/re-pair | Pairing |
| R-42 | Screenshot redaction misses sensitive content | Medium | High | Uncovered pixels/unknown window structure | Fail cloud forwarding unless redaction coverage is known, block sensitive contexts, retain no images, test adversarial fixtures | Privacy pipeline |
| R-43 | Cloud UI-tree/command export leaks unrelated private text | Medium | High | Export inspection finds chat/history text | Independent data-class consent, task-scoped minimization, opaque content references, remove unrelated text before forwarding | Privacy pipeline |

## Release-blocking invariants

A release must not proceed if any statement below is true:

1. A blocked package can receive a tap, type, screenshot, or UI-tree request.
2. A password/OTP field can be serialized, logged, or populated.
3. A duplicate `actionId` can resend a WhatsApp message.
4. An invalid session, sequence, schema, or authorization scope can reach an executor.
5. A mismatched WhatsApp target or content digest can reach Send.
6. The kill switch allows a queued action to start after one second.
7. A provider can trigger paid usage or bypass the configured daily budget.
8. Image bytes can leave the phone while phone-side export is disabled.
9. A cloud request can include an image while PC-side cloud forwarding is disabled.
10. Unattended wake-word input can authorize an external side effect.
11. Windows lock leaves an authenticated action session active.
12. Generic automation can enter an unpinned package/signer, permission controller, credential/biometric window, IME, or overlay.
13. Restored Android backup can reuse pairing credentials.
14. Unverified dependency/model/voice artifacts enter a release.
15. Cloud audio, command text, UI tree, or image leaves the device without its matching consent, or an image is forwarded with uncertain redaction coverage.

## Review cadence

- Review this register at every phase exit.
- Re-run WhatsApp and Samsung-specific risks after app, One UI, or Android updates.
- Re-check provider catalogs, quotas, and data policies monthly while actively developing.
- Add a risk whenever a test ends in `uncertain`, not only when it fails.