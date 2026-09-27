# ULTRON Setup Plan

This document defines the intended development and runtime setup. Implementation commands may change when dependency lockfiles are created.

## 1. Supported baseline

### PC

- Windows 11 x64.
- 16 GB RAM recommended; 8 GB minimum for development.
- Any modern 4-core CPU.
- NVIDIA GPU is optional, not required.
- Microphone and speaker/headphones.
- Home network set to **Private** in Windows.

CPU-only operation is the baseline. NVIDIA acceleration may improve faster-whisper latency but cannot be required because the project must remain portable.

### Phone

- Samsung device running Android 12 / API 31.
- Personally owned device with permission to sideload and enable AccessibilityService.
- Same Wi-Fi as the Windows PC.
- Phone unlocked for UI automation.

## 2. Free accounts and keys

### Required only for cloud-assisted mode

| Service | Purpose | Requirement |
|---|---|---|
| Groq | Whisper STT and preferred LLM/vision candidates | Free account and API key; verify current model access and limits in the console |

At planning time, `openai/gpt-oss-20b`, `openai/gpt-oss-120b`, and `qwen/qwen3.8-27b` are preview candidates. Preview access, behavior, and retention can change; setup must not treat them as guaranteed production dependencies.

### Optional fallback providers

| Service | Purpose | Rule |
|---|---|---|
| OpenRouter | Configured free text-model fallback | Enable only models currently marked free and tool-compatible |
| Cloudflare Workers AI | Configured text/vision fallback | Current free allocation and model eligibility must be checked before enabling |
| Cerebras | Configured text-model fallback | Use only an available legitimate free tier |

Do not create multiple accounts to bypass quotas. Do not add a billing method for automatic continuation. A fallback is enabled only after its current free status, model capabilities, privacy terms, and limits are reviewed.

Useful official references:

- Groq models: <https://console.groq.com/docs/models>
- Groq rate limits: <https://console.groq.com/docs/rate-limits>
- Groq speech-to-text: <https://console.groq.com/docs/speech-to-text>
- Groq vision: <https://console.groq.com/docs/vision>
- Cloudflare Workers AI pricing: <https://developers.cloudflare.com/workers-ai/platform/pricing/>

No Render account, public server, domain, or tunnel is needed for LAN development.

## 3. Windows development tools

Install:

1. Git for Windows.
2. Python 3.12 x64.
3. Android Studio stable with its bundled JDK 17.
4. Android SDK Platform 36 and the matching Build Tools baseline.
5. Android SDK Platform Tools (`adb`).
6. PowerShell 7, optional but recommended for scripts.
7. `uv` for Python environment and lockfile management, or standard `venv`/`pip` if the project later chooses not to use `uv`.

Verify in PowerShell:

```powershell
python --version
adb version
java -version
git --version
```

Expected baseline:

- Python reports 3.12.x.
- `adb` is available from Android SDK Platform Tools.
- Java reports 17.x for Gradle builds.

## 4. Repository bootstrap

Planned commands after source files exist:

```powershell
git clone <your-repository> <repository-directory>
Set-Location <repository-directory>\ultron

Set-Location pc-brain
uv sync --all-groups
uv run pytest

Set-Location ..\android-app
.\gradlew.bat testDebugUnitTest
.\gradlew.bat assembleDebug
```

Bootstrap pins the exact Python patch version, Gradle wrapper, AGP, Kotlin, Compose, SDK/build-tools, and dependencies in committed version/lock files. Live-provider tests stay disabled unless an explicit test flag and key are present.

## 5. PC configuration

`pc-brain/config.example.toml` should document:

```toml
mode = "local_only"
listen_host = "192.168.1.20"
listen_port = 8765
heartbeat_seconds = 15
session_idle_seconds = 45
max_task_seconds = 120
max_agent_steps = 12
allow_cloud_image_forwarding = false
audit_retention_days = 30

[models]
navigator = "openai/gpt-oss-20b"
strategist = "openai/gpt-oss-120b"
visual_observer = "qwen/qwen3.8-27b"
require_capability_probe = true

[budgets]
allow_paid = false
```

The real configuration file is untracked. Model names remain configurable because provider catalogs change. Startup probes each configured candidate for availability and required capabilities; failure disables the role or uses only an explicitly configured zero-cost fallback. `allow_cloud_image_forwarding` is an additional PC guard and cannot override the phone's image-export setting.

### Secrets

Preferred production-development flow:

- ULTRON exposes a local `secrets set` command backed by Python keyring/Windows Credential Manager.
- The PC identity private key is protected with Windows DPAPI.
- Environment variables may be used temporarily during development:

```powershell
$env:GROQ_API_KEY = "paste-key-for-this-shell-only"
```

Do not put keys in TOML, source files, screenshots, shell history, or commits. Close the shell or remove the variable after testing.

## 6. Local speech setup

### faster-whisper

Start with a quantized multilingual `small` model on CPU. Move to a smaller model if measured latency is poor; use a larger model only after testing Hinglish/name accuracy.

Profiles:

| Hardware | Suggested starting profile |
|---|---|
| CPU-only, 8 GB RAM | multilingual `base` or `small`, INT8, short utterances |
| CPU-only, 16 GB+ | multilingual `small`, INT8 |
| NVIDIA GPU | multilingual `small` or `medium`, supported CUDA quantization |

The final choice is based on measured real-time factor and the 50-command corpus, not model size alone.

### Piper

- Download one Hindi or English voice model from the selected trusted Piper release source.
- Record source, version, license, and expected SHA-256; reject a hash/signature mismatch. Apply the same provenance check to wake-word model files.
- Store model files under a local untracked data directory.
- Test Hinglish pronunciation before selecting the default voice.
- Keep text replies short and provide a mute option.

### openWakeWord

Do not enable during initial setup. Push-to-talk is the reliable baseline. A custom `Ultron` detector is added only after a measured positive/negative dataset exists.

## 7. Android project settings

Planned baseline:

- Kotlin and Jetpack Compose.
- `minSdk = 31` for Android 12.
- `compileSdk = 36`, `targetSdk = 36`, and `minSdk = 31`; exact build-tool/plugin versions are locked during bootstrap.
- Java/Kotlin toolchain 17.
- Debug APK for sideloading.

Manifest-level declarations will include only capabilities required by implemented phases, such as:

- internet/network state;
- foreground service and relevant service type permissions;
- camera for torch where required;
- accessibility service metadata;
- notifications where required on newer Android versions;
- media-projection foreground service type when that phase is implemented.

Avoid requesting SMS, contacts, call logs, storage, or other broad permissions until a specific reviewed feature needs them.

## 8. Install the debug APK

On the phone:

1. Enable Developer options.
2. Enable USB debugging for initial development installation.
3. Connect the phone by USB and approve the PC fingerprint.

On Windows:

```powershell
adb devices
.\android-app\gradlew.bat :app:installDebug
```

After installation, USB debugging may be disabled unless current development needs it. Wireless debugging is reserved for the later opt-in ADB Power Mode.

## 9. Samsung Android 12 configuration

The exact labels can vary by One UI release.

1. Open ULTRON and grant camera permission if torch control is enabled.
2. Enable ULTRON under **Settings → Accessibility → Installed apps/services**.
3. Set ULTRON battery use to **Unrestricted** or the nearest equivalent.
4. Exclude ULTRON from **Sleeping apps / Deep sleeping apps**.
5. Allow the persistent foreground-service notification.
6. Keep the phone unlocked while running UI tasks.
7. Grant MediaProjection through the Android system dialog only when the vision phase requests it.

ULTRON must display all permission/capability states and provide deep links to relevant settings where Android permits.

## 10. Windows network and firewall

1. Mark the home Wi-Fi network as **Private**, not Public.
2. Select the PC's private IPv4 address for `listen_host`.
3. Allow inbound TCP for the ULTRON Python executable or port `8765` on Private networks only.
4. Do not configure router port forwarding.
5. Do not bind the service to public adapters by default.
6. If the PC IP changes frequently, reserve it in the router or use later mDNS discovery.

A connectivity diagnostic should show:

- selected interface/address;
- WSS listening state;
- certificate fingerprint;
- phone heartbeat age;
- firewall/network-profile warning.

## 11. First pairing

1. Start the PC brain in pairing mode.
2. PC generates/loads its identity, starts WSS, and displays a two-minute QR.
3. Open ULTRON on the phone and scan the QR.
4. Confirm the displayed PC name/fingerprint during initial pairing.
5. Phone creates its Android Keystore key and proves possession.
6. PC stores the phone public key and invalidates the token.
7. Phone reconnects and opens a fresh trusted session.

After connection, allowed actions do not ask for per-action confirmation. External side effects still require an explicit typed or push-to-talk command; unattended wake-word input cannot authorize them. The session ends on disconnect or PC restart. Android permission dialogs cannot be bypassed.

## 12. Privacy-mode setup

### Local-only default

- No cloud STT or LLM calls.
- Screenshot upload disabled.
- Native commands, typed input, local STT, known local workflows, and Piper remain available.

### Enable cloud assistance

1. Add the Groq key through approved secret storage.
2. Review current provider limits and data handling.
3. Enable only the required independent toggles: **cloud audio**, **cloud command text**, **cloud UI tree**, and **cloud image**; all default off.
4. Set daily request/token budgets below the current free limits.
5. Keep every unused data class disabled. Message bodies stay local behind opaque references unless command-text export is enabled.

### Enable image export and cloud forwarding

These are two independent persistent opt-ins because screenshots may contain private data:

1. Enable **LAN image export** in the phone app. Without it, screenshot bytes never leave the phone.
2. Grant MediaProjection through Android's system dialog for the active capture session.
3. Enable `allow_cloud_image_forwarding` on the PC only if a configured visual provider may receive redacted images.

Even when both are enabled:

- blocked packages return no image;
- known sensitive regions are redacted and uncertain coverage fails closed;
- unrelated chat/history content is excluded;
- capture is resized/compressed;
- image is not retained by ULTRON;
- disabling either gate immediately prevents new cloud-image requests.

## 13. Contact enrollment

For each MVP WhatsApp recipient, the user creates a local nickname mapping, supplies or verifies a deterministic identifier such as an E.164 number, confirms the expected display name, and approves the opened chat once. ULTRON stores a stable local `contactId`; duplicate names are never auto-selected. Real contact data is untracked and excluded from logs.

## 14. Blocklist setup

The built-in non-removable categories include:

- banking and UPI/payment apps;
- password managers;
- authenticators and OTP apps;
- system credential/biometric surfaces.

The user can add more packages. The model cannot remove built-in entries. On entering a blocked package, ULTRON stops observation and action immediately.

## 15. Development verification sequence

Run in this order:

1. Python unit and protocol tests.
2. Android JVM tests.
3. Android instrumented tests on the Samsung phone.
4. WSS pairing/replay tests.
5. Typed native-action smoke tests.
6. Kill-switch and reconnect tests.
7. Voice tests with providers disabled, then optional live Groq tests.
8. WhatsApp controlled test account/contact cases.
9. Agent/provider tests with fakes before live models.
10. Privacy/redaction tests before enabling screenshot upload.

Do not use a real banking app, OTP, password, private chat history, or important contact during automation tests.

## 16. Troubleshooting checklist

### Phone cannot connect

- PC and phone are on the same Wi-Fi.
- Windows network profile is Private.
- The selected IPv4 address is reachable.
- Private-network firewall rule exists.
- Certificate fingerprint still matches; otherwise re-pair.

### Connection dies with screen off

- Foreground notification is visible.
- Samsung battery mode is Unrestricted.
- App is not in Sleeping/Deep sleeping apps.
- Heartbeat and reconnect logs identify whether Android or network ended the session.

### UI action fails

- Phone is unlocked.
- AccessibilityService is enabled and connected.
- Foreground package matches the expected app.
- Snapshot ID is current.
- Target element advertises the requested action.
- App version remains in the tested range.

### Local STT is slow

- Use short push-to-talk utterances.
- Enable VAD.
- Try a smaller quantized multilingual model.
- Verify that an optional NVIDIA profile uses the supported runtime.

### Groq request fails

- Key exists in secret storage.
- Model is currently available to the account.
- Local request/token budget is not exhausted.
- Current organization/model rate limits are checked in the Groq console.
- ULTRON should fall back or fail; it must not enable billing.

## 17. Reset and revocation

- **Stop current actions:** use the phone notification kill switch or Windows hotkey; stopped state persists and ends the session.
- **Resume after stop:** physically tap Resume in the phone app; network commands cannot clear stopped state, and a fresh session is required.
- **Disable automation:** turn off the Android foreground service and AccessibilityService.
- **Revoke PC:** unpair it in the phone app; delete the matching PC pairing record.
- **Rotate PC identity:** requires authenticated rotation or full re-pairing.
- **Remove cloud access:** delete provider keys from Windows Credential Manager and select local-only mode.
- **Delete logs:** use the planned local purge command/UI on both devices.
- **Disable Power Mode:** turn off wireless debugging and remove the ADB pairing.

## 18. Setup completion criteria

Setup is complete when:

- Windows quality/test commands run successfully;
- debug APK is installed on Samsung Android 12;
- AccessibilityService and foreground status are visible;
- QR pairing and reconnect both succeed;
- a typed volume command returns verified state;
- the phone kill switch blocks a queued action;
- no cloud key is required for the foundation demo;
- no secret or runtime artifact appears in Git status.