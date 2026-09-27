# Nixin Link protocol (v1)

One WebSocket, phone → PC: `wss://<pc>:8765/link`. UTF-8 JSON text frames, max 4 MiB. The method registry with JSON-Schema params lives in [`shared/protocol/methods.json`](../shared/protocol/methods.json); the PC validates every request against it before sending and both test suites check they match it.

## Transport security
- TLS with the PC's self-signed EC P-256 certificate. The phone **pins its SHA-256 fingerprint** (from the pairing QR) and trusts nothing else; hostnames are irrelevant.
- The phone's identity is an **EC P-256 key in the Android Keystore**. The PC stores only the public key.
- Pairing tokens: 256-bit, single use, expire after 5 minutes.
- Endpoints in a pairing code must be private (10/8, 172.16/12, 192.168/16, 100.64/10 Tailscale, loopback) and `wss://`.

## Pairing QR
`nixin://pair?d=<base64url(json)>`
```json
{"v":1,"pcId":"3c78…","pcName":"Home-PC","endpoints":["wss://192.168.1.20:8765/link","wss://100.101.1.2:8765/link"],
 "fp":"<64 hex sha256 of cert DER>","token":"<base64url 32 bytes>","exp":1790000000}
```

## Handshake
```
PC    → {"t":"hello","v":1,"pcId":"…","pcName":"Home-PC","nonce":"<b64url 32B>","server":"1.0.0"}
phone → first time:
        {"t":"pair","v":1,"deviceId":"<uuid>","token":"…","publicKey":"<b64url DER SPKI>",
         "deviceName":"samsung SM-…","model":"SM-…","sdk":31,"appVersion":"1.0.0",
         "sig":"<b64url DER ECDSA-SHA256 over 'nixin-pair\n<pcId>\n<nonce>\n<token>\n<deviceId>'>"}
        afterwards:
        {"t":"auth","v":1,"deviceId":"…","sdk":31,"appVersion":"1.0.0",
         "sig":"<… over 'nixin-auth\n<pcId>\n<nonce>\n<deviceId>'>"}
PC    → {"t":"welcome","v":1,"sessionId":"…","paired":true,"pcName":"Home-PC","heartbeatSec":15,"blocklist":[…]}
     or {"t":"denied","code":"auth.invalid_token|auth.unknown_device|auth.bad_signature|bad_request","message":"…"} + close 4001
```
A fresh nonce per connection means a recorded handshake can't be replayed. A newer connection from the same phone replaces the old one.

## Messages after welcome

| `t` | Direction | Body | Purpose |
|---|---|---|---|
| `req` | PC → phone | `id, method, params, timeoutMs, meta{taskId, origin, confirmed}` | run a method |
| `res` | phone → PC | `id, ok, result` or `id, ok:false, error{code,message}` | reply |
| `cmd` | phone → PC | `id, text, source: phone_text\|phone_voice` | you typed/spoke on the phone |
| `say` | PC → phone | `text, speak, taskId` | Nixin's reply (shown in chat, spoken if `speak`) |
| `ask` | PC → phone | `id, kind: confirm\|choose\|input, text, options[], timeoutSec` | question for you |
| `answer` | phone → PC | `id, value` | your answer ("yes"/"no"/option/text) |
| `cancel` | PC → phone | `taskId, reason` | abort in-flight work of a task |
| `event` | phone → PC | `name: status\|stopped\|resumed\|foreground, data` | state changes |
| `ping`/`pong` | both | `ts` | heartbeat: PC pings every 15 s; either side drops the link after ~60 s of silence |

Close codes: 4000 replaced, 4001 auth failed, 4005 timeout, 4006 unpaired.

## Methods

| Method | Risk | Params (see schema) | Result |
|---|---|---|---|
| `device.status` | read | – | battery, volume{stream:{level,max}}, ringer, torch, screenOn, locked, foreground, network, dnd, stopped, permissions, settings, device |
| `device.volume` | local | stream, action up\|down\|set\|mute\|unmute\|max, percent, steps | stream, previous, current, max |
| `device.torch` | local | on | on |
| `device.brightness` | local | action set\|up\|down\|auto, percent | previous, current, auto |
| `device.ringer` | local | mode | mode |
| `device.dnd` | local | on | on |
| `device.global` | nav | action back\|home\|recents\|notifications\|quick_settings\|lock_screen\|screenshot\|power_dialog\|split_screen | action |
| `device.settings` | nav | panel | opened |
| `app.list` / `app.current` | read | – | apps[] / package,label |
| `app.open` | nav | package or name | package, label |
| `intent.url` / `.search` / `.navigate` | nav | url / query+engine / destination+mode | opened |
| `intent.alarm` / `.timer` | local | hour, minute, label, days / seconds | echo |
| `media.control` | local | action | action |
| `contacts.search` | read | query, limit | contacts[{id,name,numbers[{number,label}]}] |
| `comm.call` | **external** | number | number, mode call\|dial |
| `comm.sms` | **external** | number, text | mode sent\|composer |
| `comm.whatsapp` | **external** | number, text, send, business | state sent\|composer\|uncertain, verified |
| `notif.list` | read | package, limit | notifications[{app,title,text,time}] (OTPs masked) |
| `ui.snapshot` | read | maxElements | snapshotId, package, app, title, width, height, keyboard, truncated, elements[] |
| `ui.tap` / `ui.long_press` | nav | snapshotId+elementId or x,y | tapped |
| `ui.type` | nav | text, snapshotId, elementId, clear, submit | typed |
| `ui.scroll` | nav | direction, snapshotId, elementId | scrolled |
| `ui.swipe` | nav | x1,y1,x2,y2,durationMs | swiped |
| `ui.key` | nav | key enter\|back\|home\|recents | key |
| `ui.tap_text` | nav | text, exact, index | tapped |
| `ui.wait` | read | text, package, gone, timeoutMs | matched, ms |
| `screen.capture` | read | maxWidth, quality | mime, width, height, screenWidth, screenHeight, data (base64 JPEG) |

Element format: `{"id":7,"role":"input","text":"…","desc":"…","hint":"…","res":"entry","b":[l,t,r,b],"flags":["click","edit","focus","scroll","long","sel","off","pwd"],"checked":true}`.

### Rules the phone enforces
1. Unknown method → `unknown_method`.
2. Kill switch on → everything except `device.status`/`app.list` → `policy.stopped`.
3. `external` methods need `meta.confirmed=true` → else `policy.confirmation_required`.
4. Screen methods: phone locked → `device.locked`; blocked foreground app → `policy.blocked_app`.
5. Taps on controls labelled Send/Pay/Buy/Delete/Call/Post… need `confirmed` → else `policy.confirmation_required` (the PC then asks you and retries once with `confirmed=true`).
6. Typing into password/PIN/OTP/CVV fields → `policy.sensitive_field`.
7. Timeouts: `timeout`, or `action.uncertain` for external methods (never auto-retried).
8. Duplicate request ids return the cached reply (no double execution).

Error codes are listed in `methods.json → errors`.
