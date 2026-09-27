# Nixin setup

Everything here is free. Total time: ~20 minutes.

## 1. What you need

| | |
|---|---|
| PC | Windows 11 (Linux/macOS also work), Python 3.11 or 3.12, microphone + speakers for voice |
| Phone | Android 11 or newer (tested design target: Samsung, Android 12) |
| Network | PC and phone on the same Wi-Fi (for outside-home use see §8) |
| Accounts | A free Groq key — https://console.groq.com/keys (optional extras below) |

## 2. PC brain

### Automatic (Windows)
```powershell
git clone <this repo>
cd ultro\brain
powershell -ExecutionPolicy Bypass -File ..\scripts\setup-windows.ps1
```
The script installs [uv](https://docs.astral.sh/uv/), creates `.venv`, installs Nixin with voice extras, creates `.env` and `nixin.toml` from the templates and adds a Windows Firewall rule for TCP 8765 on **Private** networks (it asks for admin).

### Manual (any OS)
```bash
cd brain
uv venv --python 3.12
uv pip install -e ".[voice]"          # add ,local-stt for offline speech-to-text, ,wakeword for "hey jarvis"
cp .env.example .env                  # put GROQ_API_KEY=... in it
cp nixin.example.toml nixin.toml      # optional; defaults are fine
```

### API keys (`brain/.env`)
Only `GROQ_API_KEY` is needed. Each extra provider adds a free fallback when Groq's per-minute limits are hit:

| Variable | Where | Used for |
|---|---|---|
| `GROQ_API_KEY` | console.groq.com/keys | gpt-oss-20b / 120b / qwen, Whisper STT |
| `CEREBRAS_API_KEY` | cloud.cerebras.ai | fast gpt-oss-120b fallback |
| `GEMINI_API_KEY` | aistudio.google.com/apikey | flash / flash-lite (text + vision) |
| `OPENROUTER_API_KEY` | openrouter.ai/keys | `:free` models |
| `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` | dash.cloudflare.com | Workers AI |

Several keys you legitimately own (e.g. separate projects) can be pooled: `GROQ_API_KEYS=key1,key2`. Don't create throwaway accounts to dodge limits — it breaks provider terms.
Prefer the OS keyring? `pip install "nixin[keyring]"` then `nixin keys set groq`.

### Check
```bash
.venv\Scripts\nixin doctor     # keys, providers, models, microphone, LAN IP, firewall hint
.venv\Scripts\nixin demo       # full brain + simulated phone + dashboard — try commands right away
```

## 3. Phone app

### Get the APK
- **Easiest:** open the repo's **Actions** tab → latest *CI* run → download artifact **nixin-debug-apk** → unzip → copy `app-debug.apk` to the phone and install (allow "install unknown apps").
- **Build yourself:** open `android/` in Android Studio and press Run, or `scripts\build-apk.ps1` then `scripts\install-apk.ps1` (USB debugging on).

### First launch
1. On the PC: `nixin run` → a QR appears in the terminal and in the dashboard (**Pair** tab).
2. On the phone: **Nixin → Setup → Scan QR** (or just scan it with the camera app — it opens Nixin).
3. The Home screen shows **Connected · <your PC>**.
4. In **Setup**, turn on:
   - **Accessibility** → Installed apps → *Nixin phone control* → On (required for apps/agent).
   - **Battery → Unrestricted** (required, or Samsung will kill the connection).
   - Notifications, Contacts, Phone, SMS, Microphone, Notification access, Modify system settings, DND access (each optional; the app explains what each unlocks).
5. **Settings → Allow screenshots** if you want the dashboard's live mirror or the agent's vision fallback.

### Samsung specifics
Settings → Apps → Nixin → Battery → **Unrestricted**. Settings → Battery → Background usage limits → remove Nixin from *Sleeping* / *Deep sleeping apps*. If the accessibility toggle keeps turning off after updates, re-enable it (Android does this for sideloaded apps after reinstall).

## 4. Using it

| Where | How |
|---|---|
| PC voice | **Ctrl+Alt+N**, speak, stop talking (auto end). Press again to cut early. |
| PC kill switch | **Ctrl+Alt+K** cancels whatever is running. |
| PC console | type commands in the `nixin run` window; `/help` for console commands |
| Dashboard | the link printed at start (localhost only, has a token) |
| Phone | Home tab: type or tap 🎤. Quick Settings tile "Nixin", or the notification's 🎤 Talk |
| Phone kill switch | notification **■ STOP** — durable; only **Resume** inside the app clears it |
| Scripts | `nixin send "torch on karo"` talks to the running brain |

Confirmations: messages and calls typed exactly ("WhatsApp pe X ko bol …") run directly; spoken ones, AI-interpreted ones and agent-initiated ones ask "bhejun?" first — answer by voice, on the phone dialog/notification, in the dashboard, or in the console. Change with `assistant.confirm` (`smart` / `trusted` / `always`).

## 5. Configuration
`brain/nixin.toml` (template: `nixin.example.toml`). Most-used knobs:
- `[assistant] reply_language`, `reply_on`, `confirm`, `default_message_channel`, `max_agent_steps`
- `[privacy] cloud_llm`, `cloud_stt`, `cloud_vision`
- `[voice] push_to_talk`, `edge_voice` (try `hi-IN-SwaraNeural`), `wake_word`
- `[models]` ordered candidates per role; `[limits."provider:model"]` your real free-tier limits
Runtime toggles are also in the dashboard → Settings.

## 6. Speech options
- **STT:** Groq Whisper (`whisper-large-v3-turbo`) by default; offline fallback with `pip install "nixin[local-stt]"` (downloads a faster-whisper model on first use; `local_stt_model = "small"` is a good CPU default).
- **TTS:** edge-tts (free neural voices, needs internet) → pyttsx3 (offline Windows voices). Piper works too: install `piper`, set `voice.piper_model` and put `"piper"` in `voice.tts`.
- **Wake word:** `pip install "nixin[wakeword]"`, `voice.wake_word = true`. Pre-trained words include "hey jarvis"; train a free custom "hey nixin" model with openWakeWord's Colab and point `wake_word_model` at the `.onnx`. Wake-word commands always confirm before sending anything.

## 7. Firewall / network
Allow inbound TCP **8765** on *Private* networks only (the setup script does this):
```powershell
New-NetFirewallRule -DisplayName "Nixin link" -Direction Inbound -Protocol TCP -LocalPort 8765 -Profile Private -Action Allow
```
Mark your home Wi-Fi as *Private* in Windows. The dashboard binds to 127.0.0.1 only. If your PC's IP changes, the phone tries every address from the QR; reserve the IP in your router or re-pair.

## 8. Using it away from home (free)
Install **Tailscale** on the PC and the phone (same account). Put the PC's Tailscale IP in `nixin.toml`:
```toml
[link]
advertise = ["100.x.y.z"]
```
Re-pair once; the phone now reaches the PC on Wi-Fi or mobile data, end-to-end encrypted, with no open ports and no server. (No Render/Cloudflare relay is needed — see DECISIONS.md.)

## 9. ADB power mode (optional)
Some things Android forbids normal apps (real Wi-Fi/Bluetooth/data toggles, screen recording, installing APKs). Enable **Developer options → Wireless debugging**, run `adb pair <ip>:<pair-port>` then `adb connect <ip>:<port>`, and set:
```toml
[adb]
enabled = true
serial = "192.168.1.23:37215"
```
Only fixed command templates exist; there is no arbitrary shell.

## 10. Troubleshooting
| Symptom | Fix |
|---|---|
| Phone says *PC offline* | same Wi-Fi? firewall rule? Wi-Fi marked Private? `nixin doctor` shows the LAN IP; try **Reconnect** |
| *certificate changed* | you deleted the data dir or rotated the cert → re-pair |
| Connection drops with screen off | Battery → Unrestricted, remove from Sleeping apps |
| Apps don't open from the PC | Accessibility must be ON (Android blocks background app launches otherwise) |
| "LLM: add a key" | put `GROQ_API_KEY` in `brain/.env`, restart |
| "AI models are busy" | free per-minute budget used up; wait a minute or add another provider key |
| Voice does nothing | `nixin doctor` → microphone; install the `voice` extra; hotkeys need the console window's user session |
| Mirror is black | Settings → Allow screenshots on the phone; secure screens (banking, DRM video) are always black |

Data locations: PC `%LOCALAPPDATA%\Nixin` (SQLite, TLS cert, identity). Phone: app storage (settings) + Android Keystore (device key). Uninstall/delete these to reset.
