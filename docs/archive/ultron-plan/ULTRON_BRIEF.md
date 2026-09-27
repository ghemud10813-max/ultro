my raw idea prompt : sun pehle ultron banate haii , as usmaii maii , groq ka , qwen 3.8 27b , use karunga , and gpt oss 120b , gpt 20b   ,multiple api dal sakuu aisaa , and kucch service wagera lagegaa toh wo render prr host krr denge connection ke liyee yaa cloud falre yaa teko koi aur best lage toh woo , and do teen task ke liyee use karenge yee teeno model , likee agenetic haii , soo inhii kee agents bana denge yahi use krke soo like that , and full control hoga phone prr , like almost sab properlyy sare controlls and all ke de properlyy aisee m and langraph wagera bhii use krr lena yaa teko joo conept lage woo wesaa , soo meko yee jo idea mene rawlyy bataya yee properly deee text mai ellaborate krkee , and think krr iskee bare mai , mera galat bhii ho sakta haii , isko fir se redefined / reform krr idea koo tere hisab see , iterate and make it more and more perfect and better and give me idea proierplyyy and all sab kuch free maii krna hai



# ULTRON — Project Brief (for planning)

You are the lead architect for this project. Read this whole brief, then produce a complete, build-ready plan. **Do not write implementation code yet.** First deliver the planning documents listed in Section 12, and ask me any clarifying questions before finalizing.

I am a 2nd-year B.Tech IT student. I want to understand the architecture, not only get code — so explain *why* for every major decision.

---

## 1. One-line vision

A voice-controlled AI agent running on my PC that can operate my Android phone like a human would — open apps, tap, type, scroll, read the screen, and complete multi-step tasks — using free LLM APIs and an agentic loop.

Example commands:
- "Volume badha do" / "Torch on karo" (simple, instant)
- "WhatsApp pe Rahul ko bol main 10 min late hoon" (multi-step)
- "Kal subah 6 baje ka alarm laga do"
- "Instagram khol aur latest notification padh ke bata"

## 2. Hard constraints

- **100% free.** No paid APIs, no paid hosting.
- **No cloud server required.** PC is the brain; phone connects to it directly.
- Android app is **sideloaded** (not for Play Store).
- Must work on the same WiFi (LAN). Remote access (outside home) is a later phase.
- Hinglish + English voice commands must work.

## 3. High-level architecture

**PC = brain. Phone = hands + eyes.**

```
[Mic] → Wake word → STT → Router ──(simple)──────────────→ Phone
                              └─(complex)→ LangGraph Agent ⇄ Phone
                                                  ↓
                                            TTS → [Speaker]
```

Communication: **WebSocket** between PC (server) and phone (client), JSON messages, authenticated with a pairing token.

## 4. Phone side (Kotlin Android app)

- **AccessibilityService**: read UI tree, perform tap/long-press/swipe/scroll, type text, global actions (back, home, recents, notifications, quick settings).
- **MediaProjection**: screenshots when the UI tree is not enough (fallback only).
- **Intents**: open apps, calls, SMS, alarms, settings pages.
- **Foreground service** to keep the WebSocket alive (handle Doze/battery optimisation).
- **Compact screen serializer**: convert the UI tree into a short text list of only useful elements, e.g. `[3] Button "Send" (540,1820)`. This is critical because of LLM token limits.
- **Kill switch**: persistent notification button that immediately stops all agent actions.
- Simple settings UI (Jetpack Compose): PC address, pairing, blocked apps list, permissions status.

Optional **power mode**: wireless ADB from PC for things Accessibility can't do (shell commands, screen recording, installing APKs). Plan how both modes coexist.

## 5. PC side (Python)

- **Wake word**: openWakeWord (offline, free).
- **STT**: Groq Whisper API, fallback to local faster-whisper.
- **Deterministic router (no LLM)**: pattern/keyword matching for simple commands (volume, torch, open app, back, home). Must respond in milliseconds and save API quota.
- **LangGraph agent** for complex tasks (see Section 6).
- **TTS**: Piper (offline) or edge-tts.
- **Memory**: SQLite — contact nicknames, recent tasks, preferences.
- **WebSocket server**: FastAPI or `websockets`.
- Optional later: small web dashboard showing live phone screen, agent steps, logs.

## 6. Agent design (LangGraph)

Three free Groq models, each with a clear role:

| Role | Model (Groq ID) | Job |
|---|---|---|
| Intent classifier | `openai/gpt-oss-20b` | Fast: understand command, pick path, extract entities |
| Planner + executor | `openai/gpt-oss-120b` | Break task into steps, call tools (tap, type, open_app, scroll, read_screen) |
| Verifier / backup | `qwen/qwen3.8-27b` | After each step, check the screen and confirm success; backup planner if limits hit |

Loop: **observe screen → decide action → execute on phone → verify → repeat** until done, failed, or max steps reached.

Requirements:
- Tool calling with a strict JSON schema for every phone action.
- Max step limit and timeouts so it never loops forever.
- Graceful failure: speak back what went wrong.
- Graph state must be inspectable (for debugging and for the dashboard).

## 7. Multi-provider LLM layer

- One common interface (OpenAI-compatible) so models/providers are swappable via config.
- Groq free tier limits are per organisation **and per model** (roughly 30 req/min, 1,000 req/day, 8,000 tokens/min, 200,000 tokens/day — verify in Groq console). Spreading work across 3 models = 3 separate budgets.
- **Fallback chain** when rate-limited or down: Groq → OpenRouter (free models) → Cloudflare Workers AI → Cerebras free. Only use legitimate free tiers; no multi-account tricks.
- Track token usage per model; keep prompts small.

## 8. Safety & security (must be designed, not bolted on)

- Pairing via one-time token/QR code; reject unknown clients.
- **Voice confirmation** before sensitive actions: sending messages, calling, deleting, sharing, anything with money.
- **Blocklist**: banking/UPI/payment apps are never touched by the agent.
- Kill switch on phone + hotkey on PC.
- Action log of everything the agent did.
- Known limits to document honestly: cannot unlock secure lock screen, FLAG_SECURE apps block screenshots, some system dialogs can't be automated.

## 9. Remote access (later phase)

Tailscale or Cloudflare Tunnel (both free). No Render/always-on server.

## 10. Build phases

1. **Foundation**: WebSocket link + Accessibility actions. Typed command on PC → tap/open app on phone. No LLM.
2. **Voice + router**: wake word, STT, deterministic commands, TTS reply.
3. **Agent**: LangGraph loop with gpt-oss-120b and compact screen reading.
4. **Reliability**: verifier model, fallback providers, memory, safety features.
5. **Extras**: remote access, ADB power mode, dashboard.

Each phase must end in a working, demoable state.

## 11. Non-goals (for now)

- iOS support
- Play Store publishing
- Controlling multiple phones
- Local LLMs running on the phone

## 12. What I want from you (deliverables)

Produce these as separate markdown files:

1. **PRD.md** — goals, user stories, features by phase, success metrics, limitations.
2. **ARCHITECTURE.md** — component diagram (mermaid), data flow for a simple command and for a multi-step command, why each tech choice was made, alternatives considered.
3. **PROTOCOL.md** — full WebSocket JSON message spec (handshake/pairing, action requests, screen snapshots, results, errors, heartbeats) with examples.
4. **AGENT_DESIGN.md** — LangGraph nodes, edges, state schema, tool definitions (JSON schemas), prompts outline, stop conditions, fallback logic.
5. **REPO_STRUCTURE.md** — monorepo layout (`/pc-brain`, `/android-app`, `/docs`, `/shared`), with the purpose of each folder/file.
6. **TASKS.md** — phase-wise checklist of small tasks (each ~1–3 hours), in build order, with acceptance criteria. I commit daily, so small tasks are important.
7. **RISKS.md** — technical risks (Android background limits, rate limits, latency, accessibility edge cases) with mitigations.
8. **SETUP.md** — free accounts/keys needed, Android permissions to enable, dev environment setup.

Before writing these, **list your clarifying questions** and any places where you think my plan is wrong or can be improved. Challenge my assumptions.
