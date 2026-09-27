// Nixin dashboard — vanilla JS, talks to /ws (live events) and /api (REST).
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const time = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

let ws = null;
let state = { snapshot: null, frame: null, ask: null };

async function api(path, opts = {}) {
  const r = await fetch(path, { credentials: "same-origin", headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}
function send(obj) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); }

// ------------------------------------------------------------------ tabs
$$(".tab").forEach((b) => b.addEventListener("click", () => {
  $$(".tab").forEach((x) => x.classList.toggle("active", x === b));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + b.dataset.tab));
  ({ tasks: loadTasks, memory: loadMemory, models: loadModels, settings: loadSettings, pair: loadDevices })[b.dataset.tab]?.();
}));

// ------------------------------------------------------------------ chat
function addMsg(role, text, meta = "") {
  if (!text) return;
  const el = $("#tplMsg").content.firstElementChild.cloneNode(true);
  el.classList.add(role);
  $(".who", el).textContent = (role === "user" ? "You" : "Nixin") + (meta ? " · " + meta : "");
  $(".text", el).textContent = text;
  $("#chat").append(el);
  $("#chat").scrollTop = 1e9;
}
$("#cmdForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const t = $("#cmd").value.trim();
  if (!t) return;
  send({ type: "command", text: t });
  $("#cmd").value = "";
});
$("#micBtn").addEventListener("click", () => send({ type: "ptt" }));
$("#stopBtn").addEventListener("click", () => send({ type: "cancel" }));
const EXAMPLES = ["volume badha do", "torch on karo", "WhatsApp kholo", "battery kitni hai", "meri latest notification padh ke bata",
  "kal subah 6 baje ka alarm laga do", "youtube pe lofi songs chalao", "Instagram pe latest post like karo"];
$("#chips").innerHTML = EXAMPLES.map((e) => `<button type="button">${esc(e)}</button>`).join("");
$$("#chips button").forEach((b) => b.addEventListener("click", () => { $("#cmd").value = b.textContent; $("#cmd").focus(); }));

// ------------------------------------------------------------------ ask (confirm / choose / input)
function showAsk(a) {
  state.ask = a;
  const box = $("#ask");
  if (!a) { box.classList.add("hidden"); box.innerHTML = ""; return; }
  let opts = "";
  if (a.kind === "confirm") opts = `<button class="primary" data-v="yes">Yes</button><button data-v="no">No</button>`;
  else if (a.kind === "choose") opts = a.options.map((o) => `<button data-v="${esc(o)}">${esc(o)}</button>`).join("") + `<button data-v="no">Cancel</button>`;
  else opts = `<input id="askInput" placeholder="Your answer"><button class="primary" data-input="1">Answer</button>`;
  box.innerHTML = `<div class="q">❓ ${esc(a.text)}</div><div class="opts">${opts}</div>`;
  box.classList.remove("hidden");
  $$("button", box).forEach((b) => b.addEventListener("click", () => {
    const v = b.dataset.input ? $("#askInput").value : b.dataset.v;
    send({ type: "answer", id: a.id, value: v });
  }));
}

// ------------------------------------------------------------------ timeline
function tl(cls, html, pre) {
  const d = document.createElement("div");
  d.className = "ev " + cls;
  d.innerHTML = `<span class="t">${time(Date.now() / 1000)}</span>${html}` + (pre ? `<pre>${esc(pre)}</pre>` : "");
  $("#timeline").append(d);
  while ($("#timeline").children.length > 300) $("#timeline").firstChild.remove();
  $("#timeline").scrollTop = 1e9;
}
function argsStr(a) { return a ? Object.entries(a).map(([k, v]) => `${k}=${typeof v === "string" ? JSON.stringify(v) : v}`).join(", ") : ""; }

function onEvent(ev, replay = false) {
  switch (ev.type) {
    case "user": if (!ev.answer && !ev.rejected) addMsg("user", ev.text, ev.source); break;
    case "say": addMsg("nixin", ev.text); break;
    case "heard": tl("", `🎙 heard: <b>${esc(ev.text)}</b> <span class="muted">(${ev.engine}${ev.confidence != null ? ", " + Math.round(ev.confidence * 100) + "%" : ""})</span>`); break;
    case "listening": setBusy(ev.on ? "Listening…" : null); break;
    case "ask": if (!replay) showAsk(ev); break;
    case "ask_closed": if (state.ask && state.ask.id === ev.id) showAsk(null); break;
    case "task":
      if (ev.status === "running") { setBusy("Working"); tl("", `▶ task <b>${esc(ev.text || "")}</b> <span class="muted">${esc(ev.source || "")}</span>`); }
      else if (ev.status !== "cancelling") { setBusy(null); tl(ev.status === "done" ? "verify" : "bad", `■ ${esc(ev.status)} via ${esc(ev.route || "?")}`); }
      break;
    case "intent": tl("", `→ ${esc(ev.kind)} <span class="muted">${esc(JSON.stringify(ev.params))}</span>`); break;
    case "classified": tl("plan", `🧠 classifier <span class="muted">${esc(ev.model)}</span>: ${ev.intents.map((i) => esc(i.kind)).join(", ")}`); break;
    case "agent": agentEvent(ev); break;
    case "action": if (ev.origin !== "agent") tl(ev.ok ? "act" : "act bad", `📱 ${esc(ev.method)} ${ev.ok ? "✓" : "✗ " + esc(ev.error || "")} <span class="muted">${ev.ms}ms</span>`); break;
    case "llm": break;
    case "log": if (ev.level !== "info" || !replay) tl(ev.level === "info" ? "" : "warn", esc(ev.msg)); break;
    case "phone": case "phone_status": refreshStatus(); break;
    case "paired": tl("verify", `🔗 paired ${esc(ev.device?.name)}`); loadDevices(); break;
    case "frame": showFrame(ev); break;
    case "frame_error": $("#mirrorHint").innerHTML = `Mirror unavailable: <b>${esc(ev.code)}</b><br><small>${esc(ev.message)}</small>`; break;
    case "settings": break;
  }
}
function agentEvent(ev) {
  switch (ev.kind) {
    case "start": tl("plan", `🤖 agent goal: <b>${esc(ev.goal)}</b> <span class="muted">(max ${ev.maxSteps} steps)</span>`); break;
    case "observe": tl("", `👁 ${esc(ev.app || ev.package)} · ${ev.elements} elements`, ev.screen); break;
    case "plan": tl(ev.valid ? "plan" : "plan bad", `💭 ${esc(ev.tool)}(${esc(argsStr(ev.args))}) <span class="muted">${esc(ev.model || "")}</span>${ev.error ? `<br><span class="bad">${esc(ev.error)}</span>` : ""}`); break;
    case "act": tl(ev.ok ? "act" : "act bad", `👉 ${ev.n}. ${esc(ev.tool)} → ${esc(ev.result)}`); break;
    case "verify": tl(ev.done === false ? "warn" : "verify", `✔ verifier: ${ev.done === false ? "not done" : "done"} — ${esc(ev.reason || "")}`); break;
    case "look": tl("plan", `🖼 vision: ${esc(ev.answer)}`); break;
    case "end": tl(ev.status === "done" ? "verify" : "bad", `🏁 ${esc(ev.status)} after ${ev.steps} steps: ${esc(ev.answer || ev.summary)}`); break;
    case "error": tl("bad", `agent error: ${esc(ev.error)}`); break;
  }
}
function setBusy(label) {
  const p = $("#busyPill");
  p.textContent = label || "Idle";
  p.className = "pill " + (label ? "busy" : "idle");
}

// ------------------------------------------------------------------ phone status + mirror
async function refreshStatus() {
  try { state.snapshot = await api("/api/status"); } catch { return; }
  const s = state.snapshot, ph = s.phone, st = ph.status || {};
  $("#pcname").textContent = `${s.pc.name} · v${s.version}`;
  const pill = $("#phonePill");
  pill.textContent = ph.connected ? `📱 ${ph.device?.name || "Phone"}` + (st.stopped ? " · STOPPED" : "") : "Phone offline";
  pill.className = "pill " + (ph.connected && !st.stopped ? "on" : "off");
  const roles = s.gateway.roles, ready = Object.values(roles).some((c) => c.some((x) => x.configured && x.available !== false));
  $("#llmPill").textContent = ready ? "LLM ready" : "LLM: add a key";
  $("#llmPill").className = "pill " + (ready ? "on" : "off");
  if (s.ask && !state.ask) showAsk(s.ask);
  const perms = st.permissions || {};
  const rows = [
    ["Battery", st.battery ? `${st.battery.level}%${st.battery.charging ? " ⚡" : ""}` : "–"],
    ["Foreground", st.foreground?.label || st.foreground?.package || "–"],
    ["Media volume", st.volume?.media ? `${st.volume.media.level}/${st.volume.media.max}` : "–"],
    ["Ringer", st.ringer || "–"],
    ["Accessibility", perms.accessibility ? "✅" : "❌ enable in phone settings"],
    ["Notifications", perms.notifications ? "✅" : "❌"],
    ["Contacts", perms.contacts ? "✅" : "❌"],
    ["Screenshots", st.settings?.allowScreenshots ? "✅ allowed" : "off (phone app setting)"],
    ["Apps synced", ph.apps || 0],
  ];
  $("#phoneStatus").innerHTML = rows.map(([k, v]) => `<span>${k}</span><b>${esc(v)}</b>`).join("");
}

function showFrame(ev) {
  state.frame = ev;
  const img = $("#mirror");
  img.src = "data:image/jpeg;base64," + ev.data;
  img.classList.remove("hidden");
  $("#mirrorHint").classList.add("hidden");
}
$("#mirrorToggle").addEventListener("change", (e) => {
  send({ type: "mirror", on: e.target.checked });
  if (!e.target.checked) { $("#mirror").classList.add("hidden"); $("#mirrorHint").classList.remove("hidden"); }
});
let drag = null;
function toScreen(e) {
  const img = $("#mirror"), r = img.getBoundingClientRect(), f = state.frame;
  if (!f) return null;
  const sw = f.screenWidth || f.width, sh = f.screenHeight || f.height;
  const scale = Math.min(r.width / sw, r.height / sh), ox = (r.width - sw * scale) / 2, oy = (r.height - sh * scale) / 2;
  const x = Math.round((e.clientX - r.left - ox) / scale), y = Math.round((e.clientY - r.top - oy) / scale);
  return x < 0 || y < 0 || x > sw || y > sh ? null : { x, y };
}
$("#mirror").addEventListener("mousedown", (e) => { drag = toScreen(e); });
$("#mirror").addEventListener("mouseup", (e) => {
  const end = toScreen(e);
  if (!drag || !end) return;
  if (Math.hypot(end.x - drag.x, end.y - drag.y) < 25) send({ type: "tap", x: drag.x, y: drag.y });
  else send({ type: "swipe", x1: drag.x, y1: drag.y, x2: end.x, y2: end.y });
  drag = null;
});
$$("[data-global]").forEach((b) => b.addEventListener("click", () => send({ type: "global", action: b.dataset.global })));

// ------------------------------------------------------------------ tasks
async function loadTasks() {
  const tasks = await api("/api/tasks?limit=100");
  $("#taskList").innerHTML = tasks.map((t) => `<div class="item" data-id="${t.task_id}">
      <div>${esc(t.text)} <span class="badge ${esc(t.status)}">${esc(t.status)}</span></div>
      <div class="meta">${new Date(t.created_at * 1000).toLocaleString()} · ${esc(t.source)} · ${esc(t.route || "")}</div></div>`).join("")
    || `<p class="muted">No tasks yet.</p>`;
  $$("#taskList .item").forEach((el) => el.addEventListener("click", () => {
    $$("#taskList .item").forEach((x) => x.classList.toggle("sel", x === el));
    loadTask(el.dataset.id);
  }));
}
async function loadTask(id) {
  const t = await api("/api/tasks/" + id);
  $("#taskDetail").innerHTML = `<h3>${esc(t.text)}</h3>
    <p><span class="badge ${esc(t.status)}">${esc(t.status)}</span> <span class="muted">${esc(t.route || "")} · ${esc(t.source)}</span></p>
    <p><b>Reply:</b> ${esc(t.summary || "")}</p>
    <div class="timeline">${t.steps.map((s) => `<div class="ev ${esc(s.kind)}"><span class="t">${time(s.ts)}</span><b>${esc(s.kind)}</b>
      <pre>${esc(JSON.stringify(s.data, null, 1))}</pre></div>`).join("")}</div>`;
}

// ------------------------------------------------------------------ memory
async function loadMemory() {
  const m = await api("/api/memory");
  $("#aliasTable").innerHTML = `<tr><th>Nickname</th><th>Contact</th><th>Number</th><th></th></tr>` + m.contacts.map((c) =>
    `<tr><td>${esc(c.alias)}</td><td>${esc(c.contact_name)}</td><td>${esc(c.number || "")}</td><td><button data-del-contact="${esc(c.alias)}">✕</button></td></tr>`).join("");
  $("#appTable").innerHTML = `<tr><th>Nickname</th><th>Package</th><th></th></tr>` + m.apps.map((a) =>
    `<tr><td>${esc(a.alias)}</td><td><code>${esc(a.package)}</code></td><td><button data-del-app="${esc(a.alias)}">✕</button></td></tr>`).join("");
  $("#factTable").innerHTML = m.facts.map((f) => `<tr><td>${esc(f.text)}</td><td><button data-del-fact="${f.id}">✕</button></td></tr>`).join("");
  $$("[data-del-contact]").forEach((b) => b.onclick = async () => { await api("/api/memory/contact/" + encodeURIComponent(b.dataset.delContact), { method: "DELETE" }); loadMemory(); });
  $$("[data-del-app]").forEach((b) => b.onclick = async () => { await api("/api/memory/app/" + encodeURIComponent(b.dataset.delApp), { method: "DELETE" }); loadMemory(); });
  $$("[data-del-fact]").forEach((b) => b.onclick = async () => { await api("/api/memory/fact/" + b.dataset.delFact, { method: "DELETE" }); loadMemory(); });
}
function formJson(f) { return Object.fromEntries(new FormData(f).entries()); }
$("#aliasForm").addEventListener("submit", async (e) => { e.preventDefault(); await api("/api/memory/contact", { method: "POST", body: JSON.stringify(formJson(e.target)) }); e.target.reset(); loadMemory(); });
$("#appForm").addEventListener("submit", async (e) => { e.preventDefault(); await api("/api/memory/app", { method: "POST", body: JSON.stringify(formJson(e.target)) }); e.target.reset(); loadMemory(); });
$("#factForm").addEventListener("submit", async (e) => { e.preventDefault(); await api("/api/memory/fact", { method: "POST", body: JSON.stringify(formJson(e.target)) }); e.target.reset(); loadMemory(); });

// ------------------------------------------------------------------ models
async function loadModels() {
  const u = await api("/api/usage");
  const roles = u.gateway.roles;
  const provs = u.gateway.providers;
  let html = `<p class="muted">Providers: ${Object.entries(provs).map(([n, p]) => `${n} <b class="${p.keys ? "ok" : "muted"}">${p.keys ? p.keys + " key" + (p.keys > 1 ? "s" : "") : "no key"}</b>`).join(" · ")}</p>`;
  for (const [role, cands] of Object.entries(roles)) {
    html += `<h3 style="margin-top:14px">${esc(role)}</h3><table><tr><th>Candidate (in order)</th><th>Status</th><th>Today</th><th>Cooldown</th></tr>` +
      cands.map((c) => `<tr><td><code>${esc(c.spec)}</code></td>
        <td>${!c.configured ? '<span class="muted">no key</span>' : c.available === false ? `<span class="bad">unavailable</span>` : c.available ? '<span class="ok">ok</span>' : "untested"}
        ${c.error ? `<br><span class="muted small">${esc(c.error)}</span>` : ""}</td>
        <td>${c.today.requests} req · ${c.today.tokens.toLocaleString()} tok</td><td>${c.cooldown > 0 ? Math.ceil(c.cooldown) + "s" : "–"}</td></tr>`).join("") + "</table>";
  }
  $("#models").innerHTML = html;
}
$("#probeBtn").addEventListener("click", async () => { $("#probeBtn").disabled = true; try { await api("/api/models/probe", { method: "POST" }); await loadModels(); } finally { $("#probeBtn").disabled = false; } });

// ------------------------------------------------------------------ settings
const SETTING_META = {
  "privacy.cloud_llm": ["Send commands + compact screen text to cloud LLMs", "bool"],
  "privacy.cloud_stt": ["Send voice audio to Groq Whisper", "bool"],
  "privacy.cloud_vision": ["Send screenshots to a vision model (agent look())", "bool"],
  "assistant.confirm": ["Confirm messages/calls", ["smart", "trusted", "always"]],
  "assistant.reply_on": ["Speak replies on", ["auto", "pc", "phone", "both"]],
  "assistant.reply_language": ["Reply language", ["auto", "hinglish", "english"]],
  "assistant.default_message_channel": ["Default message app", ["whatsapp", "sms"]],
  "assistant.verify_finish": ["Verify agent results with the verifier model", "bool"],
  "assistant.max_agent_steps": ["Max agent steps per task", "int"],
  "voice.wake_word": ["Wake word (needs restart)", "bool"],
};
async function loadSettings() {
  const s = await api("/api/settings");
  $("#settingsForm").innerHTML = Object.entries(SETTING_META).map(([k, [label, type]]) => {
    const v = s[k];
    let input;
    if (type === "bool") input = `<input type="checkbox" data-k="${k}" ${v ? "checked" : ""}>`;
    else if (type === "int") input = `<input type="number" min="3" max="40" data-k="${k}" value="${esc(v)}">`;
    else input = `<select data-k="${k}">${type.map((o) => `<option ${o === v ? "selected" : ""}>${o}</option>`).join("")}</select>`;
    return `<label for="">${esc(label)}</label><div>${input}</div>`;
  }).join("");
  $$("#settingsForm [data-k]").forEach((el) => el.addEventListener("change", async () => {
    const val = el.type === "checkbox" ? el.checked : el.type === "number" ? Number(el.value) : el.value;
    await api("/api/settings", { method: "POST", body: JSON.stringify({ [el.dataset.k]: val }) });
  }));
}

// ------------------------------------------------------------------ pairing
$("#pairBtn").addEventListener("click", async () => {
  const p = await api("/api/pair", { method: "POST" });
  $("#qr").innerHTML = p.svg;
  $("#pairInfo").innerHTML = `Expires ${new Date(p.expires * 1000).toLocaleTimeString()} · endpoints: ${p.endpoints.map(esc).join(", ")}<br>
    Certificate fingerprint: <code>${esc(p.fingerprint.slice(0, 16))}…</code><br>
    <details><summary>Copy pairing link</summary><code style="word-break:break-all">${esc(p.uri)}</code></details>`;
});
async function loadDevices() {
  const d = await api("/api/devices");
  $("#deviceTable").innerHTML = `<tr><th>Phone</th><th>Paired</th><th>Last seen</th><th></th></tr>` + d.map((x) =>
    `<tr><td>${esc(x.name)} <span class="muted small">${esc(x.model || "")}</span>${x.revoked ? ' <span class="badge failed">removed</span>' : ""}</td>
     <td>${new Date(x.paired_at * 1000).toLocaleDateString()}</td><td>${x.last_seen ? new Date(x.last_seen * 1000).toLocaleString() : "–"}</td>
     <td>${x.revoked ? "" : `<button data-unpair="${esc(x.device_id)}">Unpair</button>`}</td></tr>`).join("");
  $$("[data-unpair]").forEach((b) => b.onclick = async () => { if (confirm("Unpair this phone?")) { await api("/api/devices/" + b.dataset.unpair, { method: "DELETE" }); loadDevices(); } });
}

// ------------------------------------------------------------------ websocket
function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onmessage = (m) => {
    const ev = JSON.parse(m.data);
    if (ev.type === "hello") {
      $("#chat").innerHTML = ""; $("#timeline").innerHTML = "";
      ev.events.forEach((e) => onEvent(e, true));
      refreshStatus();
      if ($("#mirrorToggle").checked) send({ type: "mirror", on: true });
      return;
    }
    onEvent(ev);
  };
  ws.onclose = () => { $("#phonePill").textContent = "Brain disconnected"; $("#phonePill").className = "pill off"; setTimeout(connect, 2000); };
}
connect();
setInterval(refreshStatus, 15000);
