// Nixin dashboard — vanilla JS, talks to /ws (live events) and /api (REST).
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const time = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

let ws = null;
let state = { snapshot: null, frame: null, ask: null, tab: "console", notifs: [] };

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
  state.tab = b.dataset.tab;
  ({ tasks: loadTasks, memory: loadMemory, models: loadModels, settings: loadSettings, pair: loadDevices,
     automations: loadAutomations, notifications: loadNotifs, files: loadFiles, phone: loadPhone })[b.dataset.tab]?.();
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
const EXAMPLES = ["volume badha do", "torch on karo", "briefing do", "mera phone kahan hai", "mere messages summarize karo",
  "har raat 11 baje phone silent kar dena", "10 minute baad yaad dilana ki chai", "PC ka screenshot bhejo", "screen pe kya hai",
  "kal barish hogi?", "aaj maine phone kitna chalaya", "youtube pe lofi songs chalao", "Instagram pe latest post like karo"];
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
    case "routine": if (ev.status !== "running") tl(ev.status === "done" ? "verify" : "bad", `⏰ routine <b>${esc(ev.name)}</b> ${esc(ev.status)} <span class="muted">(${esc(ev.reason)})</span>`); break;
    case "routines_changed": case "skills_changed": if (state.tab === "automations" && !replay) loadAutomations(); break;
    case "recording": showRecording(ev.on ? ev.name : null); if (!replay) tl("plan", ev.on ? `🔴 teach mode: recording <b>${esc(ev.name)}</b>` : "⏹ teach mode stopped"); break;
    case "skill_step": tl("act", `🧩 ${esc(ev.skill)} ${ev.n}/${ev.total}: ${esc(ev.step)}`); break;
    case "notification": onNotification(ev.notification, replay); break;
    case "notification_removed": if (state.tab === "notifications" && !replay) loadNotifs(); break;
    case "inbox": tl("verify", `📥 from phone: ${esc(ev.item.kind === "file" ? ev.item.name : (ev.item.text || "").slice(0, 80))}`); if (state.tab === "files" && !replay) loadFiles(); break;
    case "transfer": $("#transfer").textContent = `Sending ${ev.name}: ${ev.index}/${ev.total}`; break;
    case "notify": tl("", `🔔 ${esc(ev.title)}: ${esc(ev.text)}`); break;
    case "phone_location": tl("", `📍 phone at <a href="${esc(ev.link)}" target="_blank" rel="noopener">${ev.lat.toFixed(5)}, ${ev.lon.toFixed(5)}</a>`); break;
    case "device_event": if (!replay && ["battery", "power", "call_incoming"].includes(ev.name)) tl("", `📱 ${esc(ev.name)} <span class="muted">${esc(JSON.stringify(ev.data))}</span>`); break;
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
  "voice.follow_up_seconds": ["Listen for a follow-up after Nixin asks something (seconds, 0 = off)", "float"],
  "assistant.city": ["City for weather & briefing (empty = phone location)", "text"],
  "assistant.announce_on": ["Speak routine alerts on", ["both", "pc", "phone"]],
  "bridge.clipboard_on_share": ["Text shared from the phone goes to the PC clipboard", "bool"],
  "bridge.open_links": ["Links shared from the phone open in the PC browser", "bool"],
};
async function loadSettings() {
  const s = await api("/api/settings");
  $("#settingsForm").innerHTML = Object.entries(SETTING_META).map(([k, [label, type]]) => {
    const v = s[k];
    let input;
    if (type === "bool") input = `<input type="checkbox" data-k="${k}" ${v ? "checked" : ""}>`;
    else if (type === "int") input = `<input type="number" min="3" max="40" data-k="${k}" value="${esc(v)}">`;
    else if (type === "float") input = `<input type="number" min="0" max="15" step="0.5" data-k="${k}" value="${esc(v)}">`;
    else if (type === "text") input = `<input data-k="${k}" value="${esc(v)}">`;
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

// ================================================================== v2: automations
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
$("#dayBoxes").innerHTML = DAYS.map((d, i) => `<label><input type="checkbox" name="day" value="${i + 1}"> ${d}</label>`).join("");
function describeTrigger(t) {
  switch (t.type) {
    case "time": return `⏰ ${t.at}` + (t.days?.length ? " · " + t.days.map((d) => DAYS[d - 1]).join(",") : " · daily");
    case "interval": return `🔁 every ${t.minutes} min`;
    case "once": return `📌 ${new Date(t.when * 1000).toLocaleString()}`;
    case "phrase": return "🗣 " + t.phrases.map((p) => `“${p}”`).join(" / ");
    default: return `⚡ ${t.event}` + (t.below != null ? ` < ${t.below}%` : "") + (t.contains ? ` · “${t.contains}”` : "") + (t.app ? ` · ${t.app}` : "");
  }
}
async function loadAutomations() {
  const [r, sk, pl] = await Promise.all([api("/api/routines"), api("/api/skills"), api("/api/plugins")]);
  state.routines = r.routines;
  $("select[name=event]").innerHTML = r.events.map((e) => `<option>${esc(e)}</option>`).join("");
  $("#routineTable").innerHTML = `<tr><th>Routine</th><th>When</th><th>Does</th><th>Runs</th><th></th></tr>` + r.routines.map((x) => `
    <tr><td><b>${esc(x.name)}</b><br><span class="tag ${x.enabled ? "on" : ""}">${x.enabled ? "on" : "off"}</span>
      ${x.trusted ? '<span class="tag trusted">trusted</span>' : ""}${x.builtin ? '<span class="tag">built-in</span>' : ""}</td>
      <td>${esc(describeTrigger(x.trigger))}</td><td class="acts">${esc(x.actions.join("\n"))}</td>
      <td>${x.runs}${x.last_run ? `<br><span class="muted small">${new Date(x.last_run * 1000).toLocaleString()}</span>` : ""}</td>
      <td style="white-space:nowrap"><button data-run="${x.id}" title="Run now">▶</button>
        <button data-toggle="${x.id}">${x.enabled ? "Disable" : "Enable"}</button>
        <button data-edit="${x.id}">Edit</button><button data-delr="${x.id}">✕</button></td></tr>`).join("");
  $$("[data-run]").forEach((b) => b.onclick = () => api(`/api/routines/${b.dataset.run}/run`, { method: "POST" }));
  $$("[data-toggle]").forEach((b) => b.onclick = async () => {
    const x = state.routines.find((y) => y.id === b.dataset.toggle);
    await api("/api/routines", { method: "POST", body: JSON.stringify({ ...x, enabled: !x.enabled }) }); loadAutomations();
  });
  $$("[data-edit]").forEach((b) => b.onclick = () => editRoutine(state.routines.find((y) => y.id === b.dataset.edit)));
  $$("[data-delr]").forEach((b) => b.onclick = async () => { if (confirm("Delete this routine?")) { await api("/api/routines/" + b.dataset.delr, { method: "DELETE" }); loadAutomations(); } });

  $("#autoReplay").checked = sk.autoReplay;
  showRecording(sk.recording?.name || null);
  $("#skillList").innerHTML = sk.skills.map((x) => `<div class="skill">
      <div class="rowspace"><div><b>${esc(x.name)}</b> <span class="tag">${x.kind === "auto" ? "learned route" : "taught"}</span>
        <span class="muted small">${x.steps.length} steps · ${x.runs} runs${x.fails ? ` · ${x.fails} failed` : ""}</span></div>
        <div><button data-runs="${x.id}">▶</button> <button data-dels="${x.id}">✕</button></div></div>
      <details><summary class="muted small">steps</summary><ol>${x.steps.map((st) => `<li>${esc(stepText(st))}</li>`).join("")}</ol></details></div>`).join("")
    || `<p class="muted">No skills yet.</p>`;
  $$("[data-runs]").forEach((b) => b.onclick = () => api(`/api/skills/${b.dataset.runs}/run`, { method: "POST" }));
  $$("[data-dels]").forEach((b) => b.onclick = async () => { await api("/api/skills/" + b.dataset.dels, { method: "DELETE" }); loadAutomations(); });

  $("#pluginList").innerHTML = (pl.plugins.length ? `<table><tr><th>Command</th><th>Pattern</th></tr>` + pl.plugins.map((p) =>
    `<tr><td><b>${esc(p.name)}</b><br><span class="muted">${esc(p.description)}</span></td><td><code>${esc(p.pattern)}</code></td></tr>`).join("") + "</table>"
    : `<p class="muted">No plugins. Drop a .py file into <code>${esc(pl.dirs[0])}</code> — see docs/PLUGINS.md.</p>`)
    + Object.entries(pl.errors).map(([f, e]) => `<p class="bad">⚠ ${esc(f)}</p><pre class="acts">${esc(e)}</pre>`).join("");
}
function stepText(s) {
  return { open: `open ${s.label || s.package}`, tap: `tap “${s.text || s.desc || s.res || "?"}”`, type: `type “${s.text}”`,
    scroll: `scroll ${s.dir || "down"}`, find: `scroll to “${s.text}”`, key: `press ${s.key}`, wait: `wait ${s.seconds}s` }[s.a] || s.a;
}
function showRecording(name) {
  const b = $("#recBanner");
  if (!name) { b.classList.add("hidden"); return; }
  b.innerHTML = `🔴 <b>Teach mode:</b> recording “${esc(name)}” — do it on the phone, then <button class="primary" id="recSave">Save</button>`;
  b.classList.remove("hidden");
  $("#recSave").onclick = () => api("/api/phone/teach_stop", { method: "POST" }).then(loadAutomations);
}
$("#autoReplay").addEventListener("change", (e) => api("/api/skills/auto_replay", { method: "POST", body: JSON.stringify({ on: e.target.checked }) }));
$("#reloadPlugins").addEventListener("click", () => api("/api/plugins/reload", { method: "POST" }).then(loadAutomations));
function showTrigFields() {
  const t = $("select[name=type]").value;
  $$(".routineform .trig").forEach((el) => el.classList.toggle("hidden", !el.classList.contains("trig-" + t)));
}
$("select[name=type]").addEventListener("change", showTrigFields);
$("#newRoutineBtn").addEventListener("click", () => editRoutine(null));
$("#cancelRoutine").addEventListener("click", () => $("#routineForm").classList.add("hidden"));
const F = (n) => $("#routineForm").elements.namedItem(n);
function editRoutine(x) {
  const f = $("#routineForm");
  f.reset();
  F("id").value = x?.id || "";
  if (x) {
    const t = x.trigger;
    F("name").value = x.name; F("type").value = t.type; F("at").value = t.at || "23:00";
    F("event").value = t.event || "battery_low"; F("below").value = t.below ?? ""; F("contains").value = t.contains || ""; F("app").value = t.app || "";
    F("phrases").value = (t.phrases || []).join(", "); F("minutes").value = t.minutes || "";
    if (t.when) { const d = new Date(t.when * 1000); F("date").value = d.toISOString().slice(0, 10); F("at").value = d.toTimeString().slice(0, 5); }
    $$("input[name=day]", f).forEach((c) => c.checked = (t.days || []).includes(Number(c.value)));
    F("actions").value = x.actions.join("\n"); F("trusted").checked = x.trusted; F("cooldown_minutes").value = x.cooldown_minutes;
  }
  showTrigFields();
  f.classList.remove("hidden");
  F("name").focus();
}
$("#routineForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target, type = F("type").value;
  const trigger = { type };
  if (type === "time") { trigger.at = F("at").value; trigger.days = $$("input[name=day]:checked", f).map((c) => Number(c.value)); }
  if (type === "once") trigger.when = new Date(`${F("date").value || new Date().toISOString().slice(0, 10)}T${F("at").value}`).getTime() / 1000;
  if (type === "event") { trigger.event = F("event").value; if (F("below").value) trigger.below = Number(F("below").value);
    if (F("contains").value) trigger.contains = F("contains").value; if (F("app").value) trigger.app = F("app").value; }
  if (type === "phrase") trigger.phrases = F("phrases").value.split(",").map((p) => p.trim()).filter(Boolean);
  if (type === "interval") trigger.minutes = Number(F("minutes").value || 60);
  const old = state.routines.find((y) => y.id === F("id").value) || {};
  const body = { ...old, name: F("name").value, trigger, actions: F("actions").value.split("\n").map((a) => a.trim()).filter(Boolean),
    trusted: F("trusted").checked, cooldown_minutes: Number(F("cooldown_minutes").value || 0) };
  if (!F("id").value) delete body.id;
  try { await api("/api/routines", { method: "POST", body: JSON.stringify(body) }); f.classList.add("hidden"); loadAutomations(); }
  catch (err) { alert(err.message); }
});

// ================================================================== v2: notifications
function onNotification(n, replay) {
  if (!replay) {
    tl("", `🔔 <b>${esc(n.app || n.package)}</b> ${esc(n.title)}: ${esc(n.text)}`);
    state.notifs = [n, ...state.notifs.filter((x) => x.key !== n.key)].slice(0, 60);
    const c = $("#notifCount"); c.textContent = state.notifs.length; c.classList.remove("hidden");
    if (state.tab === "notifications") renderNotifs();
  }
}
async function loadNotifs() {
  const r = await api("/api/notifications");
  state.notifs = r.items;
  for (const [k, v] of Object.entries(r.settings)) {
    const el = $(`[data-n="notifications.${k}"]`);
    if (!el) continue;
    if (el.type === "checkbox") el.checked = v; else el.value = Array.isArray(v) ? v.join(", ") : v;
  }
  renderNotifs();
}
function renderNotifs() {
  $("#notifCount").classList.add("hidden");
  $("#notifList").innerHTML = state.notifs.map((n) => `<div class="notif" data-key="${esc(n.key)}">
      <div class="head"><span class="app">${esc(n.app || n.package)}</span><b>${esc(n.title)}</b>
        <span class="muted small">${n.time ? new Date(n.time).toLocaleTimeString() : ""}</span></div>
      <div class="body">${esc(n.text)}</div>
      <div class="acts2">${n.canReply ? `<input placeholder="Reply…"><button class="primary" data-act="reply">Reply</button>` : ""}
        <button data-act="open">Open on phone</button><button data-act="dismiss">Dismiss</button></div></div>`).join("")
    || `<p class="muted">No notifications.</p>`;
  $$("#notifList .notif").forEach((el) => $$("button", el).forEach((b) => b.onclick = async () => {
    const key = el.dataset.key, act = b.dataset.act, body = { key };
    if (act === "reply") { body.text = $("input", el).value.trim(); if (!body.text) return; }
    try { await api("/api/notifications/" + act, { method: "POST", body: JSON.stringify(body) }); } catch (e) { alert(e.message); return; }
    if (act !== "open") { state.notifs = state.notifs.filter((x) => x.key !== key); renderNotifs(); }
  }));
}
$("#refreshNotifs").addEventListener("click", loadNotifs);
$("#clearNotifs").addEventListener("click", async () => { if (confirm("Clear all notifications on the phone?")) { await api("/api/notifications/dismiss", { method: "POST", body: JSON.stringify({ all: true }) }); loadNotifs(); } });
$$("[data-n]").forEach((el) => el.addEventListener("change", () => {
  const v = el.type === "checkbox" ? el.checked : el.value.split(",").map((x) => x.trim()).filter(Boolean);
  api("/api/settings", { method: "POST", body: JSON.stringify({ [el.dataset.n]: v }) });
}));

// ================================================================== v2: files
async function upload(target, file, extra = "") {
  $("#transfer").textContent = `Sending ${file.name}…`;
  const r = await fetch(`/api/files/${target}${extra}`, { method: "POST", credentials: "same-origin", body: file,
    headers: { "Content-Type": file.type || "application/octet-stream", "x-file-name": encodeURIComponent(file.name).replace(/%20/g, " ") } });
  const j = await r.json().catch(() => ({}));
  $("#transfer").textContent = r.ok ? `✓ ${file.name} ${target === "wallpaper" ? "set as wallpaper" : "sent to the phone"}` : `✗ ${j.error?.message || j.detail || r.status}`;
}
function dropZone(zone, input, target) {
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", async (e) => { e.preventDefault(); zone.classList.remove("over"); for (const f of e.dataTransfer.files) await upload(target, f); });
  input.addEventListener("change", async () => { for (const f of input.files) await upload(target, f); input.value = ""; });
}
dropZone($("#dropPhone"), $("#filePhone"), "phone");
dropZone($("#dropWall"), $("#fileWall"), "wallpaper");
$("#clipSend").addEventListener("click", async () => {
  const t = $("#clipText").value; if (!t) return;
  await fetch("/api/files/clipboard", { method: "POST", credentials: "same-origin", body: t, headers: { "Content-Type": "text/plain" } });
  $("#transfer").textContent = "✓ copied to the phone clipboard";
});
async function loadFiles() {
  const r = await api("/api/inbox");
  $("#inboxFolder").textContent = r.folder;
  $("#inboxList").innerHTML = r.items.map((i) => {
    const when = new Date(i.time * 1000).toLocaleString();
    if (i.kind === "file") {
      const img = /\.(jpe?g|png|webp)$/i.test(i.name || "");
      return `<div class="inbox-item"><span>📄</span><div class="what"><a href="/api/inbox/${i.id}/file" download>${esc(i.name)}</a>
        <div class="muted small">${when} · ${((i.size || 0) / 1024).toFixed(0)} KB</div></div>${img ? `<button data-wall="${i.id}" data-name="${esc(i.name)}">Wallpaper</button>` : ""}</div>`;
    }
    const link = i.kind === "url" ? (i.text.match(/https?:\/\/\S+/) || [""])[0] : "";
    return `<div class="inbox-item"><span>${i.kind === "url" ? "🔗" : "📝"}</span><div class="what">${link ? `<a href="${esc(link)}" target="_blank" rel="noopener">${esc(i.text)}</a>` : esc(i.text)}
      <div class="muted small">${when}</div></div><button data-copy="${esc(i.text)}">Copy</button></div>`;
  }).join("") || `<p class="muted">Nothing yet.</p>`;
  $$("[data-copy]").forEach((b) => b.onclick = () => navigator.clipboard?.writeText(b.dataset.copy));
  $$("[data-wall]").forEach((b) => b.onclick = async () => {
    const blob = await (await fetch(`/api/inbox/${b.dataset.wall}/file`, { credentials: "same-origin" })).blob();
    await upload("wallpaper", new File([blob], b.dataset.name, { type: blob.type }));
  });
}

// ================================================================== v2: phone & PC
function fmtMs(ms) { const m = Math.round((ms || 0) / 60000); return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`; }
function gb(b) { return b == null ? "?" : (b / 1024 ** 3).toFixed(1) + " GB"; }
async function loadPhone() {
  const [r, pc] = await Promise.all([api("/api/insights?period=" + $("#usagePeriod").value), api("/api/pc").catch(() => null)]);
  if (pc) $("#pcInfo").innerHTML = [["Host", pc.host], ["OS", pc.os], ["CPU", pc.cpu != null ? pc.cpu + "%" : "– (pip install psutil)"],
    ["RAM", pc.ram != null ? pc.ram + "%" : "–"], ["Battery", pc.battery != null ? pc.battery + "%" + (pc.charging ? " ⚡" : "") : "–"]]
    .map(([k, v]) => `<span>${k}</span><b>${esc(v)}</b>`).join("");
  if (!r.connected) { $("#usage").innerHTML = `<p class="muted">Phone offline.</p>`; $("#deviceInfo").innerHTML = ""; return; }
  const u = r.usage || {};
  if (u.error) $("#usage").innerHTML = `<p class="muted">${esc(u.error.message)} — grant <b>Usage access</b> to Nixin on the phone.</p>`;
  else {
    const max = Math.max(1, ...(u.apps || []).map((a) => a.ms));
    $("#usage").innerHTML = `<div class="big">${fmtMs(u.totalMs)}</div><div class="muted small">${u.unlocks ? u.unlocks + " unlocks" : ""}</div>
      <div class="bars" role="list">${(u.apps || []).map((a) => `<div class="bar" role="listitem"><span>${esc(a.label || a.package)}</span>
        <div class="track"><div class="fill" style="width:${(100 * a.ms / max).toFixed(1)}%"></div></div><span class="v">${fmtMs(a.ms)}</span></div>`).join("")}</div>`;
  }
  const i = r.info || {};
  if (!i.error) $("#deviceInfo").innerHTML = [["Model", `${i.manufacturer || ""} ${i.model || ""}`], ["Android", i.android],
    ["Storage free", `${gb(i.storage?.freeBytes)} / ${gb(i.storage?.totalBytes)}`], ["RAM free", `${gb(i.ram?.availBytes)} / ${gb(i.ram?.totalBytes)}`],
    ["Battery", i.battery ? `${i.battery.level}% · ${i.battery.health || "?"} · ${i.battery.temperatureC ?? "?"}°C` : "–"],
    ["Network", i.network ? `${i.network.type}${i.network.ssid ? " · " + i.network.ssid : ""}` : "–"],
    ["Uptime", i.uptimeMs ? fmtMs(i.uptimeMs) : "–"]].map(([k, v]) => `<span>${k}</span><b>${esc(v)}</b>`).join("");
  const p = r.playing || {};
  $("#playing").innerHTML = p.title ? `<b>${esc(p.title)}</b>${p.artist ? " — " + esc(p.artist) : ""} <span class="muted">${esc(p.app || "")} · ${esc(p.state || "")}</span>` : "Nothing playing";
}
$("#usagePeriod").addEventListener("change", loadPhone);
async function phoneAction(a) {
  try {
    const r = await api("/api/phone/" + a, { method: "POST" });
    if (a === "locate") $("#locateOut").innerHTML = r.result?.link ? `📍 <a href="${esc(r.result.link)}" target="_blank" rel="noopener">Open in Google Maps</a> (±${Math.round(r.result.accuracy || 0)} m)` : "No location";
  } catch (e) { $("#locateOut").textContent = e.message; }
}
$("#ringBtn").addEventListener("click", () => phoneAction("ring"));
$("#stopRingBtn").addEventListener("click", () => phoneAction("stop_ring"));
$("#locateBtn").addEventListener("click", () => { $("#locateOut").textContent = "Locating…"; phoneAction("locate"); });

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
