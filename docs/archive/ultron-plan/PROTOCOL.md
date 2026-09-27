# ULTRON WebSocket Protocol

**Protocol version:** `1.0`  
**Transport:** WSS over the private LAN  
**Encoding:** UTF-8 JSON text frames  
**Default port:** `8765`

## 1. Design goals

- Authenticate one paired Android phone to one Windows PC.
- Make every action typed, bounded, observable, and deduplicated.
- Reject stale sessions, replayed messages, stale UI references, and unknown fields.
- Support native actions, compact UI observations, known workflows, cancellation, and health events.
- Remain inspectable during development.

All JSON in this document is illustrative and parseable, but it is **not a cryptographic fixture**. Placeholder-looking binary values identify their encoding rather than usable key material. `/ultron/shared/protocol/examples` must be generated separately with valid UUIDs, timestamps, unpadded base64url DER/signature bytes, and matching SHA-256 values, then validated by both implementations.

## 2. Transport rules

- The phone is the WebSocket client; the PC is the server.
- TLS is mandatory. The phone pins the PC certificate SHA-256 fingerprint obtained during pairing.
- WebSocket compression is disabled for secret-bearing handshake messages and optional afterward.
- Maximum JSON frame size is **1 MiB**.
- Compact UI-tree payloads are limited to **64 KiB**.
- Encoded screenshot data is limited to **700 KiB** and must represent at most 512 KiB of compressed WebP bytes.
- Text input is limited to 4,000 Unicode code points.
- Unknown message types, fields, enum values, and action arguments are rejected.
- P-256 public keys use DER-encoded X.509 `SubjectPublicKeyInfo`; ECDSA signatures use ASN.1 DER with SHA-256.
- Binary values use unpadded RFC 4648 base64url. Signed strings use UTF-8, literal LF separators, and no trailing LF.

## 3. Common envelope

Authenticated messages use:

```json
{
  "v": "1.0",
  "type": "action.request",
  "id": "c8bb252d-9c4c-4a4d-82a4-44d4e4cff618",
  "sessionId": "6464cc53-e9cc-4981-9458-695b7bd8a16a",
  "seq": 17,
  "sentAt": "2026-09-27T11:30:00.123Z",
  "replyTo": null,
  "payload": {}
}
```

| Field | Type | Rules |
|---|---|---|
| `v` | string | Exact negotiated major/minor version |
| `type` | string | Registered message type |
| `id` | UUID string | Unique message ID |
| `sessionId` | UUID string | Required after session acceptance |
| `seq` | integer | Starts at 1 independently in each direction; because WebSocket preserves order, receiver accepts only exactly `lastAccepted + 1` |
| `sentAt` | RFC 3339 UTC string | Audited wall-clock time; validated using the handshake-derived offset/skew bound, never used alone for elapsed deadlines |
| `replyTo` | UUID or null | Message ID being answered |
| `payload` | object | Type-specific strict object |

Pairing and session-opening messages omit `sessionId` and `seq` where explicitly shown. TLS protects message integrity; session nonces and sequence numbers prevent cross-session replay.

## 4. Versioning

- Major changes are incompatible and require a new pairing/client release.
- Minor changes may add optional message types or fields only in a negotiated extension.
- During connection, each side declares `minVersion` and `maxVersion`.
- If no common version exists, the PC closes with `protocol.unsupported_version`.

## 5. Pairing QR

The PC displays a QR containing one JSON object:

```json
{
  "kind": "ultron-pairing",
  "v": "1.0",
  "endpoint": "wss://192.168.1.20:8765/ws",
  "pcId": "3c787229-3105-480e-a075-f52defc8c07a",
  "pcName": "Aarav-PC",
  "certSha256": "b8b9d14f1b7f3d7e2ddca2b310ca95f91ae6be749e6d3d6ea7b6306e6c24914d",
  "pairingToken": "base64url-256-bit-random-value",
  "expiresAt": "2026-09-27T11:32:00Z"
}
```

Rules:

- Token contains at least 256 bits of randomness.
- Token expires after two minutes and succeeds once only.
- Endpoint must be a private LAN address or approved private overlay address.
- The user must restart pairing if the certificate fingerprint differs.

## 6. Initial pairing flow

### 6.1 `pair.request` — phone to PC

```json
{
  "v": "1.0",
  "type": "pair.request",
  "id": "ac973c8b-1810-4aac-88fe-720b2246a908",
  "sentAt": "2026-09-27T11:30:10Z",
  "replyTo": null,
  "payload": {
    "pairingToken": "base64url-256-bit-random-value",
    "phonePublicKey": "base64url-unpadded-DER-X509-SubjectPublicKeyInfo",
    "device": {
      "name": "Samsung Phone",
      "manufacturer": "samsung",
      "model": "SM-XXXX",
      "androidApi": 31,
      "appVersion": "0.1.0"
    },
    "minVersion": "1.0",
    "maxVersion": "1.0"
  }
}
```

### 6.2 `pair.challenge` — PC to phone

```json
{
  "v": "1.0",
  "type": "pair.challenge",
  "id": "49e17357-a7d7-4329-a265-628ff576ef9a",
  "sentAt": "2026-09-27T11:30:10Z",
  "replyTo": "ac973c8b-1810-4aac-88fe-720b2246a908",
  "payload": {
    "pairingId": "5c573d02-25ca-4d00-8788-2644d44aec19",
    "challenge": "base64url-256-bit-random-value",
    "expiresAt": "2026-09-27T11:30:40Z"
  }
}
```

### 6.3 `pair.proof` — phone to PC

The phone signs the UTF-8 bytes of:

`ULTRON-PAIR-1\n<pcId>\n<pairingId>\n<challenge>\n1.0`

```json
{
  "v": "1.0",
  "type": "pair.proof",
  "id": "4ed38491-a2e2-46cc-8cbb-f67fb0956792",
  "sentAt": "2026-09-27T11:30:11Z",
  "replyTo": "49e17357-a7d7-4329-a265-628ff576ef9a",
  "payload": {
    "pairingId": "5c573d02-25ca-4d00-8788-2644d44aec19",
    "signature": "base64url-unpadded-ASN1-DER-ECDSA-P256-SHA256-signature"
  }
}
```

### 6.4 `pair.accept` — PC to phone

```json
{
  "v": "1.0",
  "type": "pair.accept",
  "id": "ce01786a-98f4-49f6-800b-b1b98808487c",
  "sentAt": "2026-09-27T11:30:11Z",
  "replyTo": "4ed38491-a2e2-46cc-8cbb-f67fb0956792",
  "payload": {
    "pairingId": "5c573d02-25ca-4d00-8788-2644d44aec19",
    "phoneId": "146fc55e-bc2a-45f8-9ddb-16906e633fa1",
    "pcId": "3c787229-3105-480e-a075-f52defc8c07a"
  }
}
```

The PC persists the phone public key and invalidates the token. The phone persists the pairing ID and certificate pin. No trusted action session exists yet.

## 7. Session handshake

Every new WebSocket connection creates a fresh session.

### 7.1 `session.challenge` — PC to phone

```json
{
  "v": "1.0",
  "type": "session.challenge",
  "id": "490bad84-a67f-4396-b4ac-e60732c4ccb7",
  "sentAt": "2026-09-27T11:35:00Z",
  "replyTo": null,
  "payload": {
    "pcId": "3c787229-3105-480e-a075-f52defc8c07a",
    "serverNonce": "dGhpcy1pcy1hLXN5bnRoZXRpYy0zMi1ieXRlLW5vbmNlISE",
    "serverWallTime": "2026-09-27T11:35:00.000Z",
    "serverMonotonicMs": 681234500,
    "minVersion": "1.0",
    "maxVersion": "1.0"
  }
}
```

### 7.2 `session.open` — phone to PC

The signed string is:

`ULTRON-SESSION-1\n<pcId>\n<pairingId>\n<serverNonce>\n<clientNonce>\n1.0`

```json
{
  "v": "1.0",
  "type": "session.open",
  "id": "b04ca061-f397-4856-9749-5e0a075c8dd0",
  "sentAt": "2026-09-27T11:35:00Z",
  "replyTo": "490bad84-a67f-4396-b4ac-e60732c4ccb7",
  "payload": {
    "pairingId": "5c573d02-25ca-4d00-8788-2644d44aec19",
    "clientNonce": "YW5vdGhlci1zeW50aGV0aWMtMzItYnl0ZS1ub25jZSEhIQ",
    "clientWallTime": "2026-09-27T11:35:00.300Z",
    "clientMonotonicMs": 442009100,
    "selectedVersion": "1.0",
    "signature": "base64url-unpadded-ASN1-DER-ECDSA-P256-SHA256-signature"
  }
}
```

### 7.3 `session.accept` — PC to phone

```json
{
  "v": "1.0",
  "type": "session.accept",
  "id": "2310108c-84b4-42d5-b269-3319ddcffc1d",
  "sessionId": "6464cc53-e9cc-4981-9458-695b7bd8a16a",
  "seq": 1,
  "sentAt": "2026-09-27T11:35:01Z",
  "replyTo": "b04ca061-f397-4856-9749-5e0a075c8dd0",
  "payload": {
    "heartbeatSeconds": 15,
    "idleTimeoutSeconds": 45,
    "trustedUntil": "disconnect-pc-restart-windows-lock-stop-or-revocation",
    "serverReceiveWallTime": "2026-09-27T11:35:00.500Z",
    "serverSendWallTime": "2026-09-27T11:35:01.000Z",
    "maxClockSkewMs": 5000,
    "policyRevision": "1"
  }
}
```

The trusted session uses the user's confirmation preference. By default, an exact unambiguous typed/push-to-talk WhatsApp send command is itself the authorization; the user may require an additional per-action confirmation. Wake word never authorizes external effects. Calls/share/delete always require confirmation if later added, and finance remains blocked. Disconnect, PC restart, Windows lock, unpair, certificate revocation, or kill switch ends the session.

### 7.4 Clock offset, skew, and deadlines

- The four handshake wall-clock timestamps (`serverWallTime`, `clientWallTime`, `serverReceiveWallTime`, `serverSendWallTime`) plus measured round-trip time produce an estimated peer offset and uncertainty bound. A handshake is rejected if the bound exceeds `maxClockSkewMs`; diagnostics instruct the user to correct clocks.
- `sentAt`, `deadlineAt`, and `expiresAt` are interpreted through that offset only for cross-device validation and audit. Each receiver converts an accepted remaining duration to its own monotonic clock and thereafter enforces a non-extendable local monotonic deadline.
- Wall-clock changes after acceptance never extend a deadline. Suspend/resume, Windows lock, process restart, or boot invalidates active monotonic deadlines and requires a fresh session/scope.
- Heartbeat monotonic values are opaque to the peer and are echoed only to calculate round-trip time; monotonic epochs are never compared across devices.

## 8. Capability exchange

### `capabilities.report` — phone to PC

Sent immediately after session acceptance and whenever relevant state changes.

```json
{
  "v": "1.0",
  "type": "capabilities.report",
  "id": "c429211f-a305-4b83-986f-0db5d142d8dc",
  "sessionId": "6464cc53-e9cc-4981-9458-695b7bd8a16a",
  "seq": 1,
  "sentAt": "2026-09-27T11:35:01Z",
  "replyTo": null,
  "payload": {
    "revision": 4,
    "phoneLocked": false,
    "stopped": false,
    "accessibility": "enabled",
    "mediaProjection": "consent_required",
    "privacy": {
      "lanTreeExport": true,
      "lanImageExport": false,
      "cloudAudio": false,
      "cloudCommandText": false,
      "cloudUiTree": false,
      "cloudImage": false
    },
    "systemUiObservation": "blocked",
    "observations": ["tree"],
    "actions": [
      "system.set_volume",
      "system.set_torch",
      "app.open",
      "system.global_action",
      "alarm.create",
      "ui.activate",
      "ui.input_text",
      "ui.scroll",
      "workflow.whatsapp.send_text"
    ],
    "apps": {
      "whatsapp": {
        "installed": true,
        "package": "com.whatsapp",
        "versionName": "2.26.18.75",
        "signerSha256": "4e29b8a0cf23a99e7ec066bce4b5daeb913f131088fd2ab386dc8a2a14df2090",
        "signerStatus": "pinned_match",
        "workflowSupport": "supported"
      }
    }
  }
}
```

The example reports pre-vision capabilities. When the vision-phase executor is active, the phone may additionally advertise `ui.tap_coordinate` and `ui.swipe`; their presence does not bypass image-backed snapshot or policy checks. The PC must not request a capability absent from the latest report.

## 9. Heartbeats

### `heartbeat.ping`

```json
{
  "v": "1.0",
  "type": "heartbeat.ping",
  "id": "e52a7d6b-a61e-417b-8a75-27f02a6425aa",
  "sessionId": "6464cc53-e9cc-4981-9458-695b7bd8a16a",
  "seq": 2,
  "sentAt": "2026-09-27T11:35:16Z",
  "replyTo": null,
  "payload": {"monotonicMs": 102340}
}
```

`heartbeat.pong` mirrors `monotonicMs` and replies to the ping. Missing valid traffic for 45 seconds closes the connection and expires the session.

## 10. Action lifecycle

### 10.1 `action.request` — PC to phone

```json
{
  "v": "1.0",
  "type": "action.request",
  "id": "c8bb252d-9c4c-4a4d-82a4-44d4e4cff618",
  "sessionId": "6464cc53-e9cc-4981-9458-695b7bd8a16a",
  "seq": 17,
  "sentAt": "2026-09-27T11:36:00Z",
  "replyTo": null,
  "payload": {
    "taskId": "4c39a631-f2c3-40cd-b72d-b447d73cec29",
    "actionId": "fb173d09-ded5-4c0e-b104-c5b8bf44ba57",
    "deadlineAt": "2026-09-27T11:36:10Z",
    "expectedForegroundPackage": null,
    "authorization": {
      "scopeId": "11beb2d6-7705-4ed5-aa98-70ac4404379a",
      "source": "cli",
      "riskClass": "local_change",
      "allowedActions": ["system.set_volume"],
      "allowedPackages": [],
      "allowedDataClasses": [],
      "target": null,
      "contentSha256": null,
      "commandSha256": "e1470b5bdc3a79476eea4556bd23b551c33569f8601777e1279dc62b3fa448d3",
      "expiresAt": "2026-09-27T11:36:10Z"
    },
    "action": {
      "name": "system.set_volume",
      "args": {
        "stream": "media",
        "mode": "delta_steps",
        "value": 1
      }
    }
  }
}
```

#### Authorization scope

`authorization` is required on every action request and is created once from the original command before any model call. It is immutable within a task.

| Field | Rules |
|---|---|
| `scopeId` | UUID linking all actions authorized by the same ingress decision |
| `source` | `cli`, `push_to_talk`, or `wake_word` |
| `riskClass` | `read`, `local_change`, `external_side_effect`, or `blocked` |
| `allowedActions` | Non-empty list of exact protocol action names; maximum 16 entries |
| `allowedPackages` | Exact package IDs the task may observe or manipulate; empty for package-independent native actions |
| `allowedDataClasses` | Subset of `tree`, `image`, `audio`, and `command_text`; each cloud export also requires its independent setting |
| `target` | `null` unless an external side effect is authorized; otherwise `{ "kind": "contact", "id": "contact:..." }` in MVP |
| `contentSha256` | `null` unless exact content is authorized; otherwise lowercase SHA-256 of the exact UTF-8 content bytes |
| `commandSha256` | Lowercase SHA-256 of the original command for redacted audit correlation; raw command text is not sent |
| `expiresAt` | No later than the task deadline and never more than 120 seconds after scope creation |

The phone rejects an action not named in `allowedActions`. For `workflow.whatsapp.send_text`, it additionally requires `riskClass = external_side_effect`, matching `target.id`, and a digest of the exact `text`. `wake_word` scopes cannot authorize external side effects. Scope validation is independent of model output and package policy.

### 10.2 `action.accepted` — phone to PC

```json
{
  "v": "1.0",
  "type": "action.accepted",
  "id": "b3721485-8899-4301-8dbd-8eaf6226a623",
  "sessionId": "6464cc53-e9cc-4981-9458-695b7bd8a16a",
  "seq": 8,
  "sentAt": "2026-09-27T11:36:00Z",
  "replyTo": "c8bb252d-9c4c-4a4d-82a4-44d4e4cff618",
  "payload": {
    "taskId": "4c39a631-f2c3-40cd-b72d-b447d73cec29",
    "actionId": "fb173d09-ded5-4c0e-b104-c5b8bf44ba57",
    "scopeId": "11beb2d6-7705-4ed5-aa98-70ac4404379a",
    "state": "running",
    "currentStage": "native_executing"
  }
}
```

### 10.3 `action.progress` — optional phone to PC

Used for workflows lasting more than one second. `stage` is one of `queued`, `native_executing`, `opening_app`, `locating_target`, `verifying_target`, `entering_text`, `activating_side_effect`, `verifying_result`, or `cancelling`; `percent` is an integer from 0 through 100. It never includes sensitive field content. `action.accepted.currentStage` uses the same enum.

```json
{
  "v": "1.0",
  "type": "action.progress",
  "id": "f83883fd-e095-480f-84a2-a4e1823d4f83",
  "sessionId": "6464cc53-e9cc-4981-9458-695b7bd8a16a",
  "seq": 9,
  "sentAt": "2026-09-27T11:36:03Z",
  "replyTo": "c8bb252d-9c4c-4a4d-82a4-44d4e4cff618",
  "payload": {
    "taskId": "4c39a631-f2c3-40cd-b72d-b447d73cec29",
    "actionId": "fb173d09-ded5-4c0e-b104-c5b8bf44ba57",
    "stage": "verifying_target",
    "percent": 60
  }
}
```

### 10.4 `action.result` — phone to PC

```json
{
  "v": "1.0",
  "type": "action.result",
  "id": "567028ee-b6bb-4bb2-9294-f221657402eb",
  "sessionId": "6464cc53-e9cc-4981-9458-695b7bd8a16a",
  "seq": 10,
  "sentAt": "2026-09-27T11:36:04Z",
  "replyTo": "c8bb252d-9c4c-4a4d-82a4-44d4e4cff618",
  "payload": {
    "taskId": "4c39a631-f2c3-40cd-b72d-b447d73cec29",
    "actionId": "fb173d09-ded5-4c0e-b104-c5b8bf44ba57",
    "scopeId": "11beb2d6-7705-4ed5-aa98-70ac4404379a",
    "state": "succeeded",
    "startedAt": "2026-09-27T11:36:00Z",
    "completedAt": "2026-09-27T11:36:04Z",
    "duplicate": false,
    "result": {
      "previous": 7,
      "current": 8,
      "maximum": 15
    },
    "evidence": {
      "kind": "native_state",
      "summary": "media volume changed from 7 to 8"
    }
  }
}
```

Terminal states are:

- `succeeded`
- `failed`
- `uncertain`
- `cancelled`
- `expired`

`uncertain` means an external side effect may have occurred but could not be verified. The PC must not automatically retry it.

Result/evidence objects are strict action-specific unions:

| Action | `result` | Required `evidence` |
|---|---|---|
| `system.set_volume` | `previous`, `current`, `maximum` integers | `kind=native_state`, stream and observed values |
| `system.set_torch` | `enabled` boolean | `kind=native_state`, observed torch state |
| `app.open` | logical `appId`, resulting package | `kind=foreground_package`, package and signer digest |
| `system.global_action` | performed action | `kind=accessibility_event`, resulting package/window hash |
| `alarm.create` | hour, minute, label, `nextOccurrenceLocal`, `uiShown` | `kind=intent_result`, accepted/visible state |
| `ui.activate`, `ui.input_text`, `ui.scroll`, coordinate actions | snapshot ID plus changed/no-change state | `kind=ui_postcondition`, before/after window hashes and non-sensitive summary |
| `workflow.whatsapp.send_text` | contact ID and `sendState` (`send_accepted` or `uncertain`) | `kind=workflow_postcondition`, verified package/signer/contact plus before/after hashes; no delivery claim |

Failed/cancelled/expired results use `result: null` and evidence containing only a bounded error code and safe summary. Unknown result/evidence fields are rejected.

## 11. Supported action contracts

All action objects contain exactly `name` and `args`.

| Action | Required arguments | Constraints |
|---|---|---|
| `system.set_volume` | `stream`, `mode`, `value` | Stream: `media`, `ring`, `alarm`; mode: `delta_steps`, `absolute`; bounded to device range |
| `system.set_torch` | `enabled` boolean | Native capability required |
| `app.open` | `appId` | Logical ID from configured allowlist; raw package names are not model-controlled |
| `system.global_action` | `action` | `back`, `home`, `recents`, `notifications`, `quick_settings` |
| `alarm.create` | `hour`, `minute`, optional `label`, `skipUi` | Creates the alarm clock's next occurrence in local time; `tomorrow` is accepted only when it matches that next occurrence, otherwise clarify/fail |
| `ui.activate` | `snapshotId`, `elementId`, `kind` | Kind: `click` or `long_click`; element must advertise the action |
| `ui.input_text` | `snapshotId`, `elementId`, `text`, `replace` | Editable, non-sensitive field; text max 4,000 code points |
| `ui.scroll` | `snapshotId`, `direction`, `amount`, optional `containerId` | Direction: up/down/left/right; amount 0.1–1.0 |
| `ui.tap_coordinate` | `snapshotId`, normalized `x`, normalized `y` | Vision phase only; current image-backed snapshot and allowlisted non-sensitive package required |
| `ui.swipe` | `snapshotId`, normalized `start`, normalized `end`, `durationMs` | Vision phase only; duration 100–1,500 ms and current image-backed snapshot required |
| `workflow.whatsapp.send_text` | `contactId`, `displayName`, `text` | One-to-one only; exact resolved contact; text max 4,000 |

`observe_screen` is a model-facing planning tool mapped to `observe.request`, not an `action.request`. `tap_coordinate` and `swipe` map to `ui.tap_coordinate` and `ui.swipe` and are advertised only when the vision-phase executor and image-backed snapshot checks are active.

The MVP WhatsApp scope authorizes only `workflow.whatsapp.send_text`; all opening, navigation, typing, recipient checks, and Send activation are internal phone-workflow stages. Generic UI actions cannot manipulate WhatsApp side-effect controls.

### WhatsApp request example

```json
{
  "taskId": "0ff2099f-7077-4ee0-b8c3-1ba2f5e49157",
  "actionId": "16035c9f-3cd8-4669-bb3e-e7a638e99d01",
  "deadlineAt": "2026-09-27T11:38:00Z",
  "expectedForegroundPackage": null,
  "authorization": {
    "scopeId": "e8fbfae3-7524-4cc5-a770-659588730f18",
    "source": "push_to_talk",
    "riskClass": "external_side_effect",
    "allowedActions": ["workflow.whatsapp.send_text"],
    "allowedPackages": ["com.whatsapp"],
    "allowedDataClasses": [],
    "target": {"kind": "contact", "id": "contact:rahul-sharma"},
    "contentSha256": "548b173d23344fa10afed05f3673f91aa3665247dcba979c2f478c3269e0a367",
    "commandSha256": "0f6239f0c19e2711bb7bc9ae245c473058723b1d718fbf81413536c42565553b",
    "expiresAt": "2026-09-27T11:38:00Z"
  },
  "action": {
    "name": "workflow.whatsapp.send_text",
    "args": {
      "contactId": "contact:rahul-sharma",
      "displayName": "Rahul Sharma",
      "text": "main 10 min late hoon"
    }
  }
}
```

## 12. Observation messages

### 12.1 `observe.request` — PC to phone

```json
{
  "v": "1.0",
  "type": "observe.request",
  "id": "4d80c6d2-52bb-4322-8fad-29c97982aaca",
  "sessionId": "6464cc53-e9cc-4981-9458-695b7bd8a16a",
  "seq": 18,
  "sentAt": "2026-09-27T11:36:05Z",
  "replyTo": null,
  "payload": {
    "taskId": "4c39a631-f2c3-40cd-b72d-b447d73cec29",
    "deadlineAt": "2026-09-27T11:36:15Z",
    "expectedForegroundPackage": "com.whatsapp",
    "mode": "tree",
    "maxElements": 80,
    "includeImage": false,
    "authorization": {
      "scopeId": "11beb2d6-7705-4ed5-aa98-70ac4404379a",
      "source": "cli",
      "riskClass": "read",
      "allowedActions": ["observe.request"],
      "allowedPackages": ["com.whatsapp"],
      "allowedDataClasses": ["tree"],
      "target": null,
      "contentSha256": null,
      "commandSha256": "e1470b5bdc3a79476eea4556bd23b551c33569f8601777e1279dc62b3fa448d3",
      "expiresAt": "2026-09-27T11:36:15Z"
    }
  }
}
```

`mode` is `tree`, `image`, or `auto`. Returning image bytes requires active MediaProjection and the phone-side persistent image-export setting. Forwarding those bytes from the PC to a cloud provider additionally requires the PC-side cloud-image-forwarding setting.

### 12.2 `observe.result` — phone to PC

```json
{
  "v": "1.0",
  "type": "observe.result",
  "id": "21669806-b1f4-4e93-813f-0826af21d798",
  "sessionId": "6464cc53-e9cc-4981-9458-695b7bd8a16a",
  "seq": 11,
  "sentAt": "2026-09-27T11:36:05Z",
  "replyTo": "4d80c6d2-52bb-4322-8fad-29c97982aaca",
  "payload": {
    "taskId": "4c39a631-f2c3-40cd-b72d-b447d73cec29",
    "snapshotId": "e132d4d1-78b4-42f8-9569-6dbb210ba73d",
    "capturedAt": "2026-09-27T11:36:05Z",
    "package": "com.whatsapp",
    "windowTitle": "WhatsApp",
    "windowHash": "sha256-hex",
    "locked": false,
    "truncated": false,
    "elements": [
      {
        "id": "e1",
        "role": "text",
        "text": "Rahul Sharma",
        "description": null,
        "bounds": [24, 80, 420, 150],
        "enabled": true,
        "clickable": false,
        "editable": false,
        "scrollable": false,
        "sensitive": false
      },
      {
        "id": "e7",
        "role": "button",
        "text": null,
        "description": "Send",
        "bounds": [930, 2020, 1060, 2150],
        "enabled": true,
        "clickable": true,
        "editable": false,
        "scrollable": false,
        "sensitive": false
      }
    ],
    "image": null
  }
}
```

If an image is included:

```json
{
  "mimeType": "image/webp",
  "width": 720,
  "height": 1600,
  "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "redactionsApplied": true,
  "dataBase64Url": "unpadded-base64url-encoded-webp"
}
```

Snapshot element IDs are valid only for that `snapshotId`. The phone rejects actions against a stale snapshot or changed foreground package.

## 13. Cancellation and stop state

### `task.cancel` — either direction

```json
{
  "v": "1.0",
  "type": "task.cancel",
  "id": "fa4cf281-8577-486b-9b96-7cb53adbe697",
  "sessionId": "6464cc53-e9cc-4981-9458-695b7bd8a16a",
  "seq": 19,
  "sentAt": "2026-09-27T11:36:06Z",
  "replyTo": null,
  "payload": {
    "taskId": "4c39a631-f2c3-40cd-b72d-b447d73cec29",
    "reason": "user_kill_switch"
  }
}
```

The receiver returns:

```json
{
  "v": "1.0",
  "type": "task.cancelled",
  "id": "c63db399-0ec8-4ac2-bf6e-62dd12a84114",
  "sessionId": "6464cc53-e9cc-4981-9458-695b7bd8a16a",
  "seq": 13,
  "sentAt": "2026-09-27T11:36:06Z",
  "replyTo": "fa4cf281-8577-486b-9b96-7cb53adbe697",
  "payload": {
    "taskId": "4c39a631-f2c3-40cd-b72d-b447d73cec29",
    "cancelledQueuedActions": 2,
    "inFlightState": "none",
    "reason": "user_kill_switch"
  }
}
```

`inFlightState` is `none`, `cancelling`, `completed`, or `uncertain`. The phone kill switch first persists a local stopped flag, then cancels queues and ends the session, so it works offline and survives process/device restart. Only a physical **Resume** action in the phone app may clear the flag; the phone then opens a fresh session. No network message can resume automation or replay old work.

## 14. Errors

```json
{
  "v": "1.0",
  "type": "error",
  "id": "7308d255-76e8-4a49-b950-7759c98dc8ce",
  "sessionId": "6464cc53-e9cc-4981-9458-695b7bd8a16a",
  "seq": 12,
  "sentAt": "2026-09-27T11:36:06Z",
  "replyTo": "4d80c6d2-52bb-4322-8fad-29c97982aaca",
  "payload": {
    "code": "target.stale_snapshot",
    "message": "The referenced UI snapshot is no longer current.",
    "retryable": true,
    "details": {"currentPackage": "com.whatsapp"}
  }
}
```

### Stable error codes

| Category | Codes |
|---|---|
| Protocol | `protocol.invalid_json`, `protocol.invalid_schema`, `protocol.unsupported_version`, `protocol.payload_too_large`, `protocol.unknown_type` |
| Authentication | `auth.invalid_token`, `auth.token_expired`, `auth.unpaired`, `auth.bad_signature`, `auth.replay`, `auth.session_expired`, `auth.certificate_mismatch` |
| Policy | `policy.stopped`, `policy.blocked_package`, `policy.blocked_category`, `policy.blocked_sensitive_field`, `policy.authorization_scope_invalid`, `policy.authorization_target_mismatch`, `policy.authorization_content_mismatch`, `policy.wake_word_side_effect_disallowed` |
| Device | `device.locked`, `device.offline`, `device.state_changed` |
| Permission | `permission.accessibility_disabled`, `permission.camera_missing`, `permission.media_projection_required`, `permission.notification_access_missing` |
| Capability | `capability.unsupported`, `capability.app_missing`, `capability.app_version_unsupported` |
| Target | `target.element_not_found`, `target.stale_snapshot`, `target.package_mismatch`, `target.contact_ambiguous` |
| Execution | `execution.timeout`, `execution.failed`, `execution.cancelled`, `execution.uncertain` |

Error messages are user-safe summaries. Raw stack traces remain local development logs and never cross the protocol in production mode.

## 15. Idempotency and delivery semantics

- Transport is at-least-once; exactly-once execution is not assumed.
- Every action has a globally unique `actionId` independent of the message ID.
- The phone durably stores the latest 10,000 terminal action results or seven days of results, whichever is smaller.
- A duplicate completed `actionId` returns the cached result with `duplicate: true`.
- A duplicate in-progress ID returns `action.accepted` with the current stage.
- Reusing an action ID with a different action or authorization scope returns `protocol.invalid_schema` and is audited.
- Native idempotent actions may be retried with the same ID and byte-equivalent validated payload.
- External side effects are never retried with a new ID after `uncertain`.

### Read-only reconnect reconciliation

After a fresh authenticated session, the PC may send `action.status.query` with `{ "actionId": "<uuid>" }`. The phone returns `action.status.result` with the same action ID, `state` (`unknown`, `running`, or a terminal action state), `currentStage`, and the cached terminal result when available. This exchange never accepts action arguments and can never execute or retry work. An `unknown` external side effect remains `uncertain`.

## 16. Ordering and timeout behavior

- Sequence numbers are contiguous per sender and session.
- After the first authenticated message, only the exact next sequence is accepted; lower values are replay and higher values close the ordered WebSocket session as invalid.
- Expired requests are rejected before execution.
- Default maximum action durations: native 10 seconds, UI 15 seconds, WhatsApp workflow 60 seconds.
- A whole agent task may not exceed 120 seconds.

## 17. Redaction rules

The phone must omit or replace:

- password and sensitive-field text;
- OTP/authenticator content;
- content from blocked packages;
- hidden or off-screen nodes;
- long text beyond configured limits;
- raw contact identifiers not required by the task;
- unrelated chat history, notifications, and text outside the task's allowed data class.

Cloud audio, command text, UI-tree, and image forwarding each require an independent opt-in. Exact message bodies use opaque local content references in model context unless command-text export is enabled. Image forwarding fails closed if sensitive-region redaction coverage cannot be established. Audit logs store hashes or summaries where content is unnecessary; images and audio are not retained by default.

## 18. Connection close codes

| Code | Meaning |
|---:|---|
| 4000 | Normal ULTRON session end |
| 4001 | Authentication failed |
| 4002 | Unsupported protocol version |
| 4003 | Replay or sequence violation |
| 4004 | Payload too large |
| 4005 | Session expired |
| 4006 | Device unpaired |
| 4007 | Policy stop activated |
| 4099 | Internal protocol error |

## 19. Protocol acceptance tests

- Valid pairing token can be used once; expired/reused tokens fail.
- Wrong certificate pin prevents connection before WebSocket messages.
- Wrong key signature cannot open a session.
- Replayed sequence/action messages never re-execute an action.
- Unknown fields and invalid enums fail schema validation.
- Missing, expired, action-mismatched, target-mismatched, or content-mismatched authorization scopes fail before execution.
- A wake-word scope cannot authorize an external side effect.
- Stale snapshot IDs cannot trigger UI actions.
- Coordinate taps and swipes require a current image-backed snapshot and are unavailable before the vision phase.
- Blocked packages cannot return a tree or image.
- A disconnect during WhatsApp send is reconciled with `action.status.query`; cached terminal state is returned without execution, while `unknown` remains `uncertain` and is never resent.
- Observation requests without matching package, data-class authorization, or deadline fail before collection.
- Kill switch cancels queued requests even with no network, persists stopped state, and only local phone UI can resume into a fresh session.
- PC and Android validate the same golden JSON fixtures from `/ultron/shared/protocol/examples`.