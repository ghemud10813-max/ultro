# ULTRON Build Tasks

Each task is intended to take approximately **1–3 focused hours** and produce one reviewable commit. Tasks are ordered; do not start a phase until the prior phase gate passes.

## Phase 0 — Contracts and skeleton

### P0-01 Initialize the ULTRON subproject — 1h

- Preserve the existing repository and create `/ultron/pc-brain`, `/ultron/android-app`, `/ultron/shared`, `/ultron/docs`, and `/ultron/scripts`.
- Add secret/build/runtime exclusions scoped to `/ultron`.
- **Acceptance:** clean PC and Android skeletons open successfully from `/ultron`; legacy files outside it are unchanged and no generated or secret file is tracked.

### P0-02 Freeze the MVP capability matrix — 1h

- Convert the PRD matrix into machine-readable capability names.
- Record Android 12/Samsung and WhatsApp assumptions.
- **Acceptance:** every MVP command maps to native, accessibility, workflow, ADB-only, or unsupported.

### P0-03 Define policy fixtures — 2h

- Add allowed, blocked-package, sensitive-field, immutable-authorization, wake-word, and kill-switch cases.
- **Acceptance:** fixtures cover finance, UPI, OTP, password managers, authenticators, WhatsApp target/content mismatch, wake-word side-effect rejection, and normal controls.

### P0-04 Define protocol envelope schemas — 2h

- Add strict message envelope, UUID, time, version, and sequence schemas.
- **Acceptance:** valid examples pass; unknown fields, invalid IDs, and oversize fixtures fail.

### P0-05 Define pairing and session schemas — 2h

- Add QR, pairing, challenge/proof, and session messages.
- **Acceptance:** schemas represent every handshake message in `PROTOCOL.md`.

### P0-06 Define action/result schemas — 3h

- Add authorization scope, action union, observations, coordinate/swipe restrictions, terminal states, progress, cancellation, and error codes.
- **Acceptance:** Python and Kotlin-compatible golden files exist for every action and reject missing, expired, target-mismatched, or content-mismatched authorization.

### P0-07 Create the Python skeleton — 2h

- Configure Python 3.12 project, test runner, formatter, linter, and type checker.
- **Acceptance:** one command runs an empty but passing quality suite on Windows.

### P0-08 Create the Android skeleton — 2h

- Configure Kotlin, Compose, Android 12 minimum, current compile SDK, unit/instrumented tests.
- **Acceptance:** debug APK builds and launches a placeholder status screen.

### P0-09 Add developer entry points — 2h

- Add `/ultron/README.md`, `.editorconfig`, scoped `.gitignore`, and the four PowerShell scripts named in `REPO_STRUCTURE.md`.
- **Acceptance:** README links to `docs/SETUP.md`; each script exposes help and uses only documented project paths.

### P0-10 Add shared schema validation — 2h

- Validate all protocol/model schemas, UUID/date-time formats, and golden/invalid fixtures from both language test suites.
- **Acceptance:** one command rejects unknown fields, invalid formats, and mismatched fixtures identically on Python and Kotlin.

### P0 gate

- Both projects build on Windows.
- Shared schemas validate.
- Policy fixtures are reviewed before executor code exists.

## Phase 1 — Secure LAN foundation

### P1-00A Compose the PC CLI — 3h

- Wire configuration, lifecycle, typed command parsing, status, and graceful shutdown without phone actions yet.
- **Acceptance:** CLI accepts a typed fixture, prints its parsed route, and starts/stops cleanly.

### P1-00B Add redacted audit foundation — 2h

- Record pairing, policy rejection, action lifecycle, and stop events without raw secrets/content.
- **Acceptance:** failures required by later tasks are queryable by task/action ID and fixture secrets never appear.

### P1-01 Create PC identity and TLS certificate — 3h

- Generate/load a stable PC key and self-signed local certificate.
- Protect private material with DPAPI-backed storage.
- **Acceptance:** restart preserves identity; private key is not stored in plaintext project files.

### P1-01B Generate the pairing QR — 1h

- Display endpoint, PC identity, certificate fingerprint, single-use token, and expiry from the running server.
- **Acceptance:** QR payload validates and expires after two minutes.

### P1-02 Start the private-network WSS server — 2h

- Bind FastAPI/Uvicorn to a selected private interface and configurable port.
- **Acceptance:** local health check passes; public network binding is rejected by default.

### P1-03 Build the Android pairing screen — 2h

- Scan/parse QR and display PC name, endpoint, fingerprint, and expiry.
- **Acceptance:** invalid, expired, non-WSS, and non-private endpoints are rejected.

### P1-04 Store Android device identity — 2h

- Generate P-256 key in Android Keystore and persist non-secret pairing metadata.
- **Acceptance:** key survives app restart and cannot be exported through app storage.

### P1-05 Implement the pairing proof flow — 3h

- Complete token validation, challenge, signature verification, and one-use invalidation.
- **Acceptance:** valid phone pairs; wrong signature and token reuse fail and are audited.

### P1-06 Implement reconnect session authentication — 3h

- Add challenge-response, negotiated version, session ID, and expiry on disconnect.
- **Acceptance:** paired phone reconnects without QR; replayed proof cannot open a session.

### P1-06B Add unpair and certificate rotation — 3h

- Implement local unpair/revocation and authenticated rotation-or-re-pair behavior.
- **Acceptance:** revoked phone cannot reconnect; pin change cannot be accepted silently.

### P1-06C Add on-device policy firewall — 3h

- Enforce package/signer/category/window/node/sensitive-field checks and default-deny permission controllers, credential/biometric UI, IMEs, overlays, and generic System UI.
- **Acceptance:** all policy fixtures fail before observation or execution and official allowlisted fixtures pass.

### P1-07 Add sequence, authorization, and payload guards — 3h

- Enforce per-direction sequence, frame limits, unknown-field rejection, deadlines, and immutable action authorization.
- **Acceptance:** replay, exact-next-sequence, stale, oversize, observation-data-class/package, action/target/content mismatch, and wake-word side-effect vectors behave as specified.

### P1-08 Add the Android foreground service — 3h

- Maintain WSS, status notification, heartbeat, and bounded reconnect.
- **Acceptance:** connection survives app UI closure; status remains visible.

### P1-09 Add phone kill switch — 2h

- Notification action atomically stops queued actions and ends the session.
- **Acceptance:** no queued action begins more than one second after activation, even offline.

### P1-09B Add durable local resume — 2h

- Persist stopped state and expose Resume only in physical phone UI; always create a fresh session.
- **Acceptance:** restart remains stopped and no PC/network request can clear it.

### P1-09C Add PC kill hotkey and Windows-lock suspension — 2h

- Cancel current work from a Windows hotkey and expire the session whenever Windows locks.
- **Acceptance:** both paths prevent new actions and require a fresh session.

### P1-10 Add capabilities reporting — 2h

- Report permissions, lock state, action support, app/version status, and stop state.
- **Acceptance:** PC refuses actions absent from the latest revision.

### P1-11 Implement volume action — 2h

- Add native media/ring/alarm volume action and state evidence.
- **Acceptance:** typed PC request changes media volume and returns previous/current values.

### P1-12 Implement torch action — 2h

- Add camera permission/status and native torch control.
- **Acceptance:** on/off succeeds when available and returns a specific unavailable/permission error otherwise.

### P1-13 Implement app-open and global actions — 3h

- Add logical app allowlist plus back/home/recents/notification/quick-settings actions.
- **Acceptance:** raw model-controlled package strings are impossible; supported actions work on the target phone.

### P1-14 Implement alarm intent — 2h

- Add bounded time/label parsing and `ACTION_SET_ALARM` execution.
- **Acceptance:** a test alarm is created or Android UI is opened with an honest result.

### P1-15 Add action dedupe cache — 3h

- Persist action ID, argument hash, state, and terminal result.
- **Acceptance:** duplicate ID returns cached result; same ID with different args is rejected.

### P1-15B Add read-only action reconciliation — 2h

- Implement `action.status.query/result` against the durable dedupe cache.
- **Acceptance:** reconnect can recover cached state without executing; unknown external effects remain uncertain.

### P1-16 Run Samsung background test — 2h

- Test screen-off, app-closed, Wi-Fi interruption, and reconnect behavior.
- **Acceptance:** observed limits and required Samsung battery setting are recorded; no old action is replayed.

### P1 gate

Typed Windows commands securely control native phone actions over LAN, survive a normal reconnect, and stop locally through the notification.

## Phase 2 — Voice and deterministic router

### P2-01 Build normalization corpus — 2h

- Add at least 50 English/Hinglish variants for five command families.
- **Acceptance:** fixtures preserve names/message text while normalizing command words.

### P2-02 Implement volume/torch routes — 2h

- Map bounded phrases to native action objects.
- **Acceptance:** positive/negative fixtures pass without an LLM.

### P2-03 Implement app/navigation routes — 2h

- Map app aliases and global navigation phrases.
- **Acceptance:** unknown apps remain unresolved rather than becoming raw packages.

### P2-04 Implement alarm route — 3h

- Parse 12/24-hour Hinglish/English times using Android alarm intent's next-occurrence semantics.
- **Acceptance:** `tomorrow` works only when it matches the next occurrence; conflicts and unclear times ask for clarification.

### P2-05 Add push-to-talk capture — 3h

- Register a Windows hotkey, capture one utterance, apply VAD, and emit WAV/PCM.
- **Acceptance:** start/stop cues work and no background recording occurs outside activation.

### P2-06 Add Groq Whisper adapter — 2h

- Read key from approved secret storage and return provider, derived, or null confidence metadata.
- **Acceptance:** live test is opt-in; missing key falls back, and null confidence cannot authorize an external effect.

### P2-07 Add faster-whisper fallback — 3h

- Support CPU baseline and optional CUDA profile.
- **Acceptance:** one English and one Hinglish command transcribe offline on the Windows machine.

### P2-08 Add confidence and clarification gate — 2h

- Block low-confidence external-side-effect commands.
- **Acceptance:** ambiguous contact/message audio cannot reach execution.

### P2-09 Add Piper TTS — 2h

- Queue short success/failure replies and allow mute.
- **Acceptance:** replies work offline and do not overlap.

### P2-10 Integrate voice happy paths — 3h

- Run STT → router → phone → result → TTS.
- **Acceptance:** agreed command corpus reaches at least 95% deterministic routing accuracy.

### P2 gate

Five command families work by voice without an LLM, and cloud STT failure demonstrably falls back locally.

## Phase 3 — Accessibility and WhatsApp workflow

### P3-01 Add AccessibilityService lifecycle — 2h

- Declare service metadata, connect/disconnect status, and global action adapter.
- **Acceptance:** app reports exact enabled/disabled state and refuses UI tasks when disabled.

### P3-02 Build compact UI serializer — 3h

- Emit useful visible nodes, roles, bounds, action flags, and snapshot IDs.
- **Acceptance:** synthetic tree stays under limits and excludes invisible/duplicate nodes.

### P3-03 Add sensitive-node redaction — 2h

- Remove password/sensitive text and blocked-package content.
- **Acceptance:** all leak fixtures produce no sensitive value.

### P3-04 Implement semantic element activation — 3h

- Click/long-click by snapshot-scoped element ID.
- **Acceptance:** stale ID, changed package, disabled element, and unsupported action fail closed.

### P3-05 Implement safe text input — 3h

- Focus editable element and set/replace text.
- **Acceptance:** non-sensitive test input works; password/OTP fields are rejected.

### P3-06 Implement bounded scroll — 2h

- Prefer semantic scroll action and bounded gesture fallback.
- **Acceptance:** one scroll changes the tree hash; repeated no-progress is reported.

### P3-07 Add observation protocol — 2h

- Connect tree request/result messages to PC fake-agent CLI.
- **Acceptance:** PC prints a compact redacted tree and cannot reference old snapshots.

### P3-08 Add contact enrollment and management — 3h

- Create/edit/delete a local nickname mapping to stable `contactId`, user-verified E.164/workflow identifier, and expected display name.
- **Acceptance:** unique enrolled identity resolves; duplicate/unknown identity asks for clarification and real identifiers never enter logs.

### P3-09 Detect WhatsApp capability/version — 2h

- Report installed package, signer digest, version, and supported workflow status.
- **Acceptance:** absent, signer-mismatched, or untested version fails with a specific capability result.

### P3-09B Parse WhatsApp commands and freeze scope — 2h

- Extract recipient/exact text, clarify ambiguity, and create a workflow-only target/content authorization scope before any model call.
- **Acceptance:** mismatch and low/null-confidence speech cannot start the workflow.

### P3-10 Open WhatsApp and locate contact — 3h

- Build initial workflow stages with semantic selectors.
- **Acceptance:** workflow reaches a unique test contact or terminates as ambiguous/not found.

### P3-11 Verify chat identity — 2h

- Match visible chat title to resolved identity before text entry.
- **Acceptance:** deliberate wrong-chat fixture stops without typing.

### P3-12 Enter exact WhatsApp text — 2h

- Populate the composer without rewriting the user's content.
- **Acceptance:** test text matches code point-for-code point and is not sent yet.

### P3-13 Enforce dedicated Send path — 2h

- Block generic activation of recognized WhatsApp side-effect controls.
- **Acceptance:** generic `ui.activate` cannot tap Send; workflow action can proceed.

### P3-14 Send once and verify — 3h

- Recheck package/signer/contact, validate target and exact-text digest, activate Send, and compare before/after evidence.
- **Acceptance:** matching visible outgoing state returns `send_accepted` (not delivered); mismatch never taps Send, and timeout/reconnect never duplicates.

### P3-15 Run controlled WhatsApp trial set — 3h

- Execute 20 agreed one-to-one cases including duplicate names and failure states.
- **Acceptance:** at least 18 succeed, all ambiguity cases stop, duplicates remain zero.

### P3 gate

The trusted-session voice command can send one exact one-to-one WhatsApp message on the tested phone/version with recipient verification and duplicate protection.

## Phase 4 — Bounded LangGraph agent

### P4-01 Define provider capability interface — 2h

- Model chat/tool/vision capability, timeout, privacy, and zero-cost eligibility.
- **Acceptance:** fake providers with mismatched capabilities are rejected.

### P4-02 Implement Groq text adapter — 3h

- Add request/response translation for configured Navigator/Strategist candidates and probe model availability plus tool-output compatibility at startup.
- **Acceptance:** live tests are explicitly enabled, unavailable preview IDs fail clearly or use an explicitly configured eligible fallback, and tool output reaches schema validation.

### P4-03 Add usage budgets and circuit breaker — 3h

- Track requests/tokens per provider/model and honor retry timing.
- **Acceptance:** simulated 429/budget exhaustion cannot exceed configured limits or select paid usage.

### P4-04 Implement graph state and terminal guards — 3h

- Add typed state, 12-step/120-second limits, cancellation, and no-progress counters.
- **Acceptance:** fake infinite task always terminates within limits.

### P4-05 Implement graph routing nodes — 2h

- Connect ingest, deterministic route, entity resolution, and policy precheck.
- **Acceptance:** direct commands still bypass models.

### P4-06 Implement observation and Navigator nodes — 3h

- Minimize context and require strict one-action output.
- **Acceptance:** valid fake proposal advances; invented element/tool fails validation.

### P4-07 Implement validator and dispatch nodes — 3h

- Validate schema, capability, snapshot, explicit side effect, and package policy.
- **Acceptance:** invalid action never reaches fake or real phone.

### P4-08 Implement deterministic verification — 3h

- Evaluate native state, package, element, workflow evidence, and screen hashes.
- **Acceptance:** success, failure, and ambiguity fixtures classify correctly.

### P4-09 Add Strategist escalation — 2h

- Escalate only on configured complexity/recovery triggers.
- **Acceptance:** normal task uses no 120B call; forced recovery uses at most one escalation cycle.

### P4-10 Add SQLite checkpoints — 3h

- Persist redacted graph state after actions and terminal events.
- **Acceptance:** inspection survives restart without replaying an old action.

### P4-11 Add prompt-injection tests — 2h

- Place hostile instructions in UI text and model responses.
- **Acceptance:** policy and tool surface remain unchanged in every case.

### P4-12 Run bounded agent demo — 3h

- Complete one multi-step non-sensitive navigation task and exercise each terminal condition.
- **Acceptance:** trace shows node, action, verification, usage, and final reason.

### P4 gate

Agent tasks are inspectable, bounded, schema-safe, policy-safe, and do not reduce deterministic-command reliability.

## Phase 5 — Vision, privacy, and provider resilience

### P5-00 Add privacy settings UI — 3h

- Expose independent cloud-audio, command-text, UI-tree, LAN-image-export, and cloud-image toggles, all off by default.
- **Acceptance:** disabling any toggle immediately blocks that data class; settings survive restart without storing content.

### P5-01 Add MediaProjection consent flow — 3h

- Implement Android-controlled consent, foreground type, active state, and explicit stop.
- **Acceptance:** capture cannot start without consent and ends cleanly.

### P5-02 Add image resize/compression limits — 2h

- Produce bounded WebP frames and reject oversized output.
- **Acceptance:** encoded image respects protocol limits on the target resolution.

### P5-03 Add image redaction and blocked-context guard — 3h

- Mask known sensitive nodes before export and block sensitive packages.
- **Acceptance:** redaction fixtures pass; blocked app returns no image.

### P5-04 Implement configured visual verifier — 3h

- Probe the configured vision candidate, send an image only when both phone export and PC cloud forwarding are enabled, and require the verdict-only schema.
- **Acceptance:** verifier cannot emit an executable action; either disabled gate sends no bytes; unavailable preview model fails clearly or uses an explicitly configured eligible fallback.

### P5-05 Add OpenRouter fallback adapter — 3h

- Enable only explicitly configured free, capability-compatible models.
- **Acceptance:** shared fake/live contract passes and paid models are rejected.

### P5-05B Add Cloudflare Workers AI adapter — 3h

- Implement its distinct auth/capability mapping behind the common interface.
- **Acceptance:** shared contract passes and local budgets prevent paid usage.

### P5-05C Add Cerebras fallback adapter — 3h

- Implement text-role support only when a legitimate free tier is configured.
- **Acceptance:** shared contract passes and unsupported roles fail clearly.

### P5-06 Add audit retention and purge — 2h

- Redact, cap, expire, export, and purge action records.
- **Acceptance:** 30-day/size policy works and exported log contains no fixture secrets.

### P5-07 Add failure dashboard view — 3h

- Show connection, task node, action/result, provider usage, and terminal reason locally.
- **Acceptance:** dashboard exposes no secrets/raw sensitive observations.

### P5-08 Prepare reliability soak — 2h

- Script Wi-Fi loss, screen off, Doze, provider failure, Windows lock, and PC sleep cases with redacted artifacts.
- **Acceptance:** each scenario has expected bounds and a clean reset path.

### P5-09 Run reliability soak — 1h active plus unattended runtime

- Run the reviewed scenarios for the agreed duration without active implementation work.
- **Acceptance:** complete timestamped results are captured without private content.

### P5-10 Analyze reliability soak — 2h

- Classify failures and verify duplicate/reconnect/action bounds.
- **Acceptance:** no duplicate side effect, runaway loop, or unbounded reconnect remains; otherwise the phase gate fails.

### P5 gate

Vision is optional and privacy-gated; provider failure degrades safely; logs are useful without retaining sensitive data.

## Phase 6 — Optional extras

### P6-01 Collect wake-word samples — 2h

- Build positive/negative `Ultron` dataset without private speech retention.
- **Acceptance:** dataset consent and deletion process are documented.

### P6-02 Integrate openWakeWord — 3h

- Add activation threshold, audible cue, and disable switch.
- **Acceptance:** evaluation meets an agreed false-accept/false-reject target before default enablement.

### P6-03 Add Tailscale profile — 2h

- Bind to the approved private overlay interface and repeat session tests.
- **Acceptance:** remote operation works without port forwarding/public WSS exposure.

### P6-04 Design ADB command templates — 2h

- List exact allowed commands and per-command policy.
- **Acceptance:** no template accepts arbitrary shell fragments.

### P6-05 Implement ADB Power Mode lifecycle — 3h

- Add explicit enable/disable, device allowlist, indicator, and audit.
- **Acceptance:** disabled mode exposes no ADB capability; wrong device is rejected.

### P6-06 Add one ADB-only capability — 2h

- Implement and test a single justified template.
- **Acceptance:** arguments are typed/bounded and kill switch prevents new execution.

## Final release checklist

- [ ] Windows setup works from a clean machine.
- [ ] Debug APK installs and pairs on Samsung Android 12.
- [ ] Protocol contract tests pass on Python and Kotlin.
- [ ] Deterministic command corpus reaches its target.
- [ ] WhatsApp controlled trials reach target with zero duplicates.
- [ ] All release-blocking invariants in `RISKS.md` pass.
- [ ] No secret, real contact, raw screenshot, audio, or runtime database is tracked.
- [ ] Local-only mode works with all provider keys removed.
- [ ] Every phase has a demo recording/log and one clear rollback point.