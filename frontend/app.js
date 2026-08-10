/* Sehat Saathi v2 — app logic */
const $ = id => document.getElementById(id);
let TOKEN = localStorage.getItem("ss_token") || "";
let USER = null;
let mockMode = false;

const api = async (path, opts = {}) => {
  const r = await fetch(path, {
    ...opts,
    headers: { "Content-Type": "application/json", "Authorization": "Bearer " + TOKEN, ...(opts.headers || {}) },
  });
  if (r.status === 401 && !path.includes("login") && !path.includes("register")) { doLogout(false); throw new Error("401"); }
  if (!r.ok) throw Object.assign(new Error("api"), { status: r.status, detail: (await r.json().catch(() => ({}))).detail });
  return r.json();
};
const toast = t => { const el = $("toast"); el.textContent = t; el.classList.add("show"); setTimeout(() => el.classList.remove("show"), 2600); };
const esc = s => { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; };

/* ================= AUTH ================= */
let authMode = "login";
$("tabLogin").onclick = () => setAuthMode("login");
$("tabReg").onclick = () => setAuthMode("reg");
function setAuthMode(m) {
  authMode = m;
  $("tabLogin").classList.toggle("on", m === "login");
  $("tabReg").classList.toggle("on", m === "reg");
  $("regFields").classList.toggle("hide", m === "login");
  $("authBtn").textContent = m === "login" ? "Login karein" : "Account banayein";
  $("authErr").classList.remove("show");
}
$("authBtn").onclick = doAuth;
$("aPass").addEventListener("keydown", e => { if (e.key === "Enter") doAuth(); });
async function doAuth() {
  const phone = $("aPhone").value.trim(), pass = $("aPass").value;
  const err = $("authErr");
  try {
    const body = authMode === "login"
      ? { phone, password: pass }
      : { phone, password: pass, name: $("rName").value.trim() || "Saathi", caregiver_phone: $("rCare").value.trim() };
    const res = await api("/api/" + (authMode === "login" ? "login" : "register"), { method: "POST", body: JSON.stringify(body) });
    TOKEN = res.token; USER = res.user;
    localStorage.setItem("ss_token", TOKEN);
    enterApp();
  } catch (e) {
    err.textContent = e.detail || "Kuch galat hua — dobara koshish karein";
    err.classList.add("show");
  }
}
function doLogout(callApi = true) {
  if (callApi) api("/api/logout", { method: "POST" }).catch(() => {});
  TOKEN = ""; USER = null; localStorage.removeItem("ss_token");
  $("appView").classList.add("hide"); $("authView").classList.remove("hide");
}
$("logoutBtn").onclick = () => doLogout();

async function boot() {
  try { const h = await fetch("/api/health").then(r => r.json());
    mockMode = h.mode === "mock";
    $("modeSub").textContent = mockMode ? "MOCK MODE (dev)" : "LIVE · Rime + Qdrant + HF";
  } catch (e) { $("modeSub").textContent = "server offline"; }
  if (TOKEN) {
    try { USER = (await api("/api/me")).user; enterApp(); return; } catch (e) {}
  }
  $("authView").classList.remove("hide");
}
function enterApp() {
  $("authView").classList.add("hide"); $("appView").classList.remove("hide");
  $("greetName").textContent = `Namaste, ${USER.name} ji! 🙏`;
  $("greetDate").textContent = new Date().toLocaleDateString("hi-IN", { weekday: "long", day: "numeric", month: "long" });
  if (recog) recog.lang = (USER.lang === "en") ? "en-IN" : "hi-IN";
  refreshDashboard(); refreshReminders(); refreshMemories();
  startDuePolling(); startCountdown();
}

/* ================= NAV ================= */
document.querySelectorAll(".nav button").forEach(b => {
  b.onclick = () => {
    document.querySelectorAll(".nav button").forEach(x => x.classList.toggle("on", x === b));
    ["home", "saathi", "alarm", "yaad"].forEach(v => $("view-" + v).classList.toggle("hide", v !== b.dataset.v));
    if (b.dataset.v === "home") refreshDashboard();
    if (b.dataset.v === "alarm") refreshReminders();
    if (b.dataset.v === "yaad") refreshMemories();
  };
});

/* ================= DASHBOARD ================= */
let nextDoseTime = null;
async function refreshDashboard() {
  try {
    const d = await api("/api/dashboard");
    $("streakN").textContent = d.streak;
    // next dose
    if (d.next_dose) {
      $("ndMed").textContent = d.next_dose.label;
      nextDoseTime = d.next_dose.time_hhmm;
    } else { $("ndMed").textContent = "Sab ho gaya ✓"; nextDoseTime = null; $("ndCount").firstChild.textContent = "🎉"; }
    // today list
    const box = $("todayList"); box.innerHTML = "";
    if (!d.today.length) box.innerHTML = '<p class="empty">Alarm tab se ya Saathi se bol kar dawai ka samay set karein.</p>';
    for (const m of d.today) {
      const row = document.createElement("div");
      row.className = "medrow" + (m.taken ? " done" : "");
      row.innerHTML = `<span class="t">${m.time_hhmm}</span><span class="n">${esc(m.label)}</span>`;
      const btn = document.createElement("button");
      btn.className = "tickbtn" + (m.taken ? " done" : "");
      btn.textContent = m.taken ? "Ho gaya ✓" : "Le li ✓";
      if (!m.taken) btn.onclick = async () => { await markTaken(m.label); };
      row.appendChild(btn); box.appendChild(row);
    }
    // week bars
    const wb = $("weekBars"); wb.innerHTML = "";
    const max = Math.max(1, ...d.week.map(x => x.taken));
    for (const w of d.week) {
      wb.insertAdjacentHTML("beforeend",
        `<div class="wb"><div class="bar" style="height:${(w.taken / max) * 92 + 5}px" title="${w.taken}"></div><span class="d">${w.date}</span></div>`);
    }
  } catch (e) {}
}
async function markTaken(label) {
  await api("/api/adherence/mark", { method: "POST", body: JSON.stringify({ label }) });
  toast(`${label} — le li ✓`);
  refreshDashboard(); refreshMemories();
}
function startCountdown() {
  setInterval(() => {
    if (!nextDoseTime) return;
    const [hh, mm] = nextDoseTime.split(":").map(Number);
    const t = new Date(); t.setHours(hh, mm, 0, 0);
    let diff = (t - new Date()) / 1000;
    if (diff < 0) { $("ndCount").firstChild.textContent = "abhi!"; return; }
    const h = Math.floor(diff / 3600), m = Math.floor((diff % 3600) / 60);
    $("ndCount").firstChild.textContent = (h ? h + "h " : "") + m + "m";
  }, 1000);
}

/* ================= REMINDERS ================= */
async function refreshReminders() {
  try {
    const d = await api("/api/reminders");
    const box = $("remList"); box.innerHTML = "";
    if (!d.reminders.length) { box.innerHTML = '<p class="empty">Koi alarm nahi. Neeche se add karein — ya Saathi se boliye "subah 8 baje yaad dilana".</p>'; return; }
    for (const r of d.reminders) {
      const row = document.createElement("div");
      row.className = "remrow" + (r.active ? "" : " off");
      row.innerHTML = `<span class="time">${r.time_hhmm}</span><span class="n">${esc(r.label)}<small>${r.days === "daily" ? "roz" : esc(r.days)}</small></span>`;
      const sw = document.createElement("button");
      sw.className = "switch" + (r.active ? " on" : ""); sw.title = "on/off";
      sw.onclick = async () => { await api(`/api/reminders/${r.id}?active=${r.active ? "false" : "true"}`, { method: "PATCH" }); refreshReminders(); refreshDashboard(); };
      const del = document.createElement("button");
      del.className = "delbtn"; del.textContent = "✕"; del.title = "Delete";
      del.onclick = async () => { await api(`/api/reminders/${r.id}`, { method: "DELETE" }); refreshReminders(); refreshDashboard(); };
      row.appendChild(sw); row.appendChild(del); box.appendChild(row);
    }
  } catch (e) {}
}
$("remAdd").onclick = async () => {
  const label = $("remLabel").value.trim() || "Dawai";
  const t = $("remTime").value;
  if (!t) return toast("Samay chunein");
  await api("/api/reminders", { method: "POST", body: JSON.stringify({ label, time_hhmm: t }) });
  $("remLabel").value = "";
  toast(`⏰ ${label} — ${t} set`);
  refreshReminders(); refreshDashboard();
};

/* due polling → overlay + voice */
let overlayQueue = [];
function startDuePolling() {
  setInterval(async () => {
    try {
      const d = await api("/api/reminders/due");
      for (const r of d.due) { overlayQueue.push(r); }
      if (overlayQueue.length && $("remOverlay").classList.contains("hide")) showNextOverlay();
    } catch (e) {}
  }, 20000);
}
function showNextOverlay() {
  const r = overlayQueue.shift(); if (!r) return;
  $("ovMed").textContent = r.label;
  $("ovText").textContent = r.speak_text;
  $("remOverlay").classList.remove("hide");
  // chime + speak
  playChime();
  if (r.audio_b64) new Audio(`data:${r.content_type || "audio/mp3"};base64,${r.audio_b64}`).play().catch(() => {});
  else { const u = new SpeechSynthesisUtterance(r.speak_text); u.lang = "hi-IN"; speechSynthesis.speak(u); }
  $("ovTaken").onclick = async () => { $("remOverlay").classList.add("hide"); await markTaken(r.label); showNextOverlay(); };
  $("ovLater").onclick = () => { $("remOverlay").classList.add("hide"); toast("Theek hai, baad mein"); showNextOverlay(); };
}
function playChime() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    [0, .18, .36].forEach((t, i) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.connect(g); g.connect(ctx.destination);
      o.frequency.value = [660, 880, 990][i]; o.type = "sine";
      g.gain.setValueAtTime(.22, ctx.currentTime + t);
      g.gain.exponentialRampToValueAtTime(.001, ctx.currentTime + t + .45);
      o.start(ctx.currentTime + t); o.stop(ctx.currentTime + t + .5);
    });
  } catch (e) {}
}

/* ================= SAATHI (voice) ================= */
let state = "idle", currentAudio = null, speakingMeta = null, heardContext = "", speechEndAt = 0;
function setState(s, label) {
  state = s;
  $("orbWrap").className = "orb-wrap " + (s === "idle" ? "" : s);
  const labels = { idle: "तैयार हूँ", listening: "सुन रही हूँ…", thinking: "सोच रही हूँ…", speaking: "बोल रही हूँ — बीच में बोल सकते हैं" };
  $("stateBadge").textContent = label || labels[s] || s;
  const btn = $("talkBtn");
  if (s === "listening") { btn.textContent = "⏹ रुकिए"; btn.classList.add("stop"); }
  else { btn.textContent = "🎙 बोलिए"; btn.classList.remove("stop"); }
}
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let recog = null;
if (SR) {
  recog = new SR();
  recog.lang = "hi-IN"; recog.interimResults = true; recog.continuous = false;
  recog.onresult = e => {
    let interim = "", final = "";
    for (const r of e.results) (r.isFinal ? final += r[0].transcript : interim += r[0].transcript);
    if (state === "speaking" && (interim.trim() || final.trim())) bargeIn();
    $("caption").innerHTML = esc(final) + ' <span class="interim">' + esc(interim) + "</span>";
    if (final.trim()) { speechEndAt = performance.now(); sendTurn(final.trim()); }
  };
  recog.onend = () => { if (state === "listening") setState("idle"); };
  recog.onerror = ev => { if (ev.error !== "no-speech" && ev.error !== "aborted") console.warn("STT:", ev.error); if (state === "listening") setState("idle"); };
} else {
  $("caption").textContent = "इस ब्राउज़र में voice input नहीं है — Chrome इस्तेमाल करें। नीचे के बटन फिर भी चलेंगे।";
}
$("talkBtn").onclick = () => {
  if (state === "speaking") { bargeIn(); return; }
  if (state === "listening") { recog && recog.stop(); setState("idle"); return; }
  heardContext = ""; try { recog && recog.start(); setState("listening"); } catch (e) {}
};
document.querySelectorAll(".chip").forEach(c => c.onclick = () => { speechEndAt = performance.now(); sendTurn(c.dataset.say); });

function bargeIn() {
  if (currentAudio && speakingMeta) {
    const frac = currentAudio.duration ? Math.min(1, currentAudio.currentTime / currentAudio.duration) : 0;
    heardContext = speakingMeta.text.slice(0, Math.round(speakingMeta.text.length * frac));
    currentAudio.pause(); currentAudio = null;
  } else if (speakingMeta && window.speechSynthesis) {
    const elapsed = (performance.now() - speakingMeta.startedAt) / 1000;
    const est = Math.min(1, elapsed / (speakingMeta.text.length / 14));
    heardContext = speakingMeta.text.slice(0, Math.round(speakingMeta.text.length * est));
    speechSynthesis.cancel();
  }
  speakingMeta = null; setState("listening");
}

async function sendTurn(transcript) {
  addMsg("user", transcript);
  setState("thinking");
  const t0 = performance.now();
  let res;
  try {
    res = await api("/api/converse", { method: "POST", body: JSON.stringify({ transcript, heard_context: heardContext }) });
  } catch (e) {
    addMsg("bot", "Server se sampark nahi ho paya. Kripya dobara koshish karein.");
    setState("idle"); return;
  }
  heardContext = "";
  const netMs = Math.round(performance.now() - t0) - (res.timings_ms?.server_total_ms || 0);
  $("escBanner").classList.toggle("show", !!res.escalated);
  $("caption").textContent = res.say;
  addMsg("bot", res.say, res.voice);
  renderHits(res.retrieved);
  refreshMemories();
  // agent actions may have changed reminders / adherence
  if ((res.memory_events || []).some(e => ["reminder_set", "adherence_marked"].includes(e.event))) {
    refreshReminders(); refreshDashboard();
    const rs = res.memory_events.find(e => e.event === "reminder_set");
    if (rs) toast(`⏰ ${rs.label} — ${rs.time_hhmm} set`);
  }
  playReply(res, () => {
    const total = Math.round(performance.now() - speechEndAt);
    renderLatency(res.timings_ms || {}, Math.max(netMs, 0), total);
  });
}
function playReply(res, onFirstAudio) {
  setState("speaking");
  speakingMeta = { text: res.say, startedAt: performance.now() };
  if (recog) { try { recog.start(); } catch (e) {} }
  if (res.audio_b64) {
    currentAudio = new Audio(`data:${res.content_type || "audio/mp3"};base64,${res.audio_b64}`);
    currentAudio.onplaying = onFirstAudio;
    currentAudio.onended = () => { currentAudio = null; speakingMeta = null; if (state === "speaking") setState("idle"); };
    currentAudio.play().catch(() => setState("idle"));
    $("voicePill").textContent = `voice: ${res.voice?.speaker || "?"} · ${res.voice?.model || ""}`;
  } else {
    const u = new SpeechSynthesisUtterance(res.say);
    u.lang = res.lang === "hi" ? "hi-IN" : "en-IN";
    u.onstart = onFirstAudio;
    u.onend = () => { speakingMeta = null; if (state === "speaking") setState("idle"); };
    speechSynthesis.speak(u);
    $("voicePill").textContent = "voice: browser (mock)";
  }
}
function addMsg(kind, text, voice) {
  const d = document.createElement("div");
  d.className = "msg " + kind;
  d.innerHTML = `<div class="who">${kind === "user" ? "आप" : "स"}</div><div class="txt">${esc(text)}` +
    (voice && voice.speaker ? `<em>${esc(voice.speaker + " · " + (voice.model || ""))}</em>` : "") + "</div>";
  $("feed").appendChild(d);
  $("feed").scrollTop = $("feed").scrollHeight;
}

/* ================= MEMORY / DEV ================= */
function renderHits(retrieved) {
  const box = $("hits"); box.innerHTML = "";
  const mems = retrieved?.memories || [], know = retrieved?.knowledge || [];
  if (!mems.length && !know.length) { box.innerHTML = '<p class="empty">Is turn mein koi retrieval nahi.</p>'; return; }
  for (const m of mems) box.insertAdjacentHTML("beforeend",
    `<div class="hit"><span class="score">memory · ${m.score?.toFixed?.(2) ?? ""}</span><br>${esc(m.text)}</div>`);
  for (const k of know) box.insertAdjacentHTML("beforeend",
    `<div class="hit k"><span class="score">knowledge · ${k.score?.toFixed?.(2) ?? ""}</span><br>${esc(k.text)}</div>`);
}
async function refreshMemories() {
  try {
    const data = await api("/api/memories");
    const box = $("memList"); box.innerHTML = "";
    if (!data.memories.length) { box.innerHTML = '<p class="empty">अभी कोई याद नहीं।</p>'; return; }
    for (const m of data.memories) {
      const d = document.createElement("div");
      d.className = "mem" + (m.active === "false" ? " inactive" : "");
      d.innerHTML = `<div>${esc(m.text)}<span class="tag">${esc(m.mem_type)}${m.active === "false" ? " · superseded" : ""}</span></div>`;
      const del = document.createElement("button");
      del.textContent = "✕"; del.title = "Delete memory"; del.className = "delbtn";
      del.onclick = async () => { await api(`/api/memories/${m.id}`, { method: "DELETE" }); refreshMemories(); };
      d.appendChild(del); box.appendChild(d);
    }
  } catch (e) {}
}
function renderLatency(t, netMs, totalMs) {
  const rows = [["STT (browser)", Math.max(totalMs - netMs - (t.server_total_ms || 0), 0)],
    ["Qdrant", t.qdrant_ms || 0], ["LLM", t.llm_ms || 0], ["Rime TTS", t.tts_ms || 0], ["network", netMs]];
  const max = Math.max(totalMs, 1);
  let html = "";
  for (const [lbl, v] of rows)
    html += `<div class="lat-row"><span class="lbl">${lbl}</span><div class="bar" style="width:${Math.max(v / max * 100, 2)}%"></div><span>${v}ms</span></div>`;
  html += `<div class="lat-row total"><span class="lbl">USER TOTAL</span><div class="bar" style="width:100%"></div><span>${totalMs}ms</span></div>`;
  $("lat").innerHTML = html;
}

boot();
