"use strict";
/* DateSwipe frontend — vanilla JS, mobile-first SPA */
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let ME = null;            // own profile
let STACK = [];           // discover profiles
let CHAT = null;          // {match_id, other}
let lastSignalId = 0;
let msgTimer = null, sigTimer = null;

async function api(path, opts = {}) {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const data = await r.json().catch(() => ({}));
  if (r.status === 401) { showAuth(); throw new Error("login"); }
  return { status: r.status, data };
}
const post = (p, b) => api(p, { method: "POST", body: JSON.stringify(b || {}) });

function toast(msg) {
  const t = $("toast");
  t.textContent = msg; t.style.display = "block";
  clearTimeout(t._h); t._h = setTimeout(() => (t.style.display = "none"), 2600);
}
function avatarHTML(p, size) {
  if (p.photos && p.photos.length)
    return `<img class="avatar" src="${esc(p.photos[0])}" alt="">`;
  const ch = esc((p.name || "?")[0].toUpperCase());
  return `<div class="avatar"${size ? ` style="width:${size}px;height:${size}px"` : ""}>${ch}</div>`;
}

/* ---------------------------------------------------------- views */
function showView(id) {
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("on"));
  $(id).classList.add("on");
  const btns = [...document.querySelectorAll("#nav button")];
  btns.forEach((b) => b.classList.toggle("on", b.dataset.v === id));
  const i = btns.findIndex((b) => b.dataset.v === id);
  if (i >= 0) $("navInd").style.left = `calc(${i * 25}% + 6px)`;
  window.scrollTo(0, 0);
}
function showAuth() {
  ME = null;
  $("nav").style.display = "none";
  showView("v-auth");
}
function showMain() {
  $("nav").style.display = "flex";
  showView("v-discover");
  loadDiscover();
}

/* ---------------------------------------------------------- auth */
$("tabLogin").onclick = () => {
  $("tabLogin").classList.add("on"); $("tabSignup").classList.remove("on");
  $("formLogin").style.display = ""; $("formSignup").style.display = "none";
};
$("tabSignup").onclick = () => {
  $("tabSignup").classList.add("on"); $("tabLogin").classList.remove("on");
  $("formSignup").style.display = ""; $("formLogin").style.display = "none";
};
$("btnLogin").onclick = async () => {
  $("authErr").textContent = "";
  const { status, data } = await post("/api/login",
    { email: $("liEmail").value.trim(), password: $("liPass").value });
  if (!data.ok) { $("authErr").textContent = data.error || "Login failed"; return; }
  ME = data.user; showMain();
};
$("btnSignup").onclick = async () => {
  $("authErr").textContent = "";
  const { status, data } = await post("/api/signup", {
    name: $("suName").value.trim(), email: $("suEmail").value.trim(),
    password: $("suPass").value, birthdate: $("suDob").value,
    gender: $("suGender").value, looking_for: $("suLooking").value,
    referral_code: $("suRef").value.trim(),
  });
  if (!data.ok) { $("authErr").textContent = data.error || "Signup failed"; return; }
  const me = await api("/api/me");
  ME = me.data.user; showMain();
  toast("Welcome to DateSwipe! 💘");
};

/* ---------------------------------------------------------- nav */
document.querySelectorAll("#nav button").forEach((b) => {
  b.onclick = () => {
    const v = b.dataset.v;
    if (v === "v-discover") loadDiscover();
    if (v === "v-matches") loadMatches();
    if (v === "v-invite") loadInvite();
    if (v === "v-profile") loadProfile();
    showView(v);
  };
});

/* ---------------------------------------------------------- discover */
async function loadDiscover() {
  const box = $("stack");
  box.innerHTML = `<div class="scard skel" style="position:absolute;inset:0"></div>`;
  const { data } = await api("/api/discover");
  STACK = data.profiles || [];
  renderStack();
}
function renderStack() {
  const box = $("stack");
  box.innerHTML = "";
  if (!STACK.length) {
    box.innerHTML = `<div class="empty"><span class="big">🌙</span>
      <b>That's everyone for now!</b><br>New people join every day — check back soon,
      or invite friends and earn Premium. 💫
      <div class="cta"><button class="btn" onclick="loadInvite();showView('v-invite')">
      💰 Invite &amp; Earn</button></div></div>`;
    return;
  }
  // 3 stacked cards with depth: top card interactive, on top
  [2, 1, 0].forEach((i) => {
    if (i >= STACK.length) return;
    const p = STACK[i];
    const card = cardEl(p);
    card.style.zIndex = 10 + (2 - i);
    if (i > 0) {
      card.style.transform = `scale(${1 - i * 0.045}) translateY(${i * 16}px)`;
      card.style.opacity = 1 - i * 0.25;
      card.style.pointerEvents = "none";
    }
    box.appendChild(card);
  });
  makeDraggable(box.lastChild, STACK[0]);
}
function chipsHTML(interests) {
  const items = (interests || "").split(",").map((s) => s.trim()).filter(Boolean).slice(0, 4);
  if (!items.length) return "";
  return `<div class="chips">${items.map((t) => `<span class="chip">${esc(t)}</span>`).join("")}</div>`;
}
function cardEl(p) {
  const d = document.createElement("div");
  d.className = "scard";
  const media = p.photos.length
    ? `<img src="${esc(p.photos[0])}" alt="" draggable="false">`
    : `<div class="noimg">${esc((p.name || "?")[0].toUpperCase())}</div>`;
  d.innerHTML = `${media}<div class="scrim"></div>
    <div class="stamp like">LIKE</div><div class="stamp nope">NOPE</div>
    <div class="stamp super">⭐ SUPER</div>
    <div class="info"><div class="nm">${esc(p.name)} <span>${p.age == null ? "" : p.age}</span></div>
      <div class="bio">${esc(p.bio) || '<span style="opacity:.6">No bio yet</span>'}</div>
      ${chipsHTML(p.interests)}</div>`;
  return d;
}
function makeDraggable(card, profile) {
  let sx = 0, sy = 0, dx = 0, dy = 0, dragging = false;
  const like = card.querySelector(".stamp.like"), nope = card.querySelector(".stamp.nope");
  const show = (el, v) => {
    el.style.opacity = Math.min(1, v);
    el.style.transform = `${el.classList.contains("nope") ? "rotate(12deg)" : "rotate(-12deg)"} scale(${0.6 + Math.min(1, v) * 0.5})`;
  };
  card.addEventListener("pointerdown", (e) => {
    dragging = true; sx = e.clientX; sy = e.clientY;
    card.setPointerCapture(e.pointerId);
    card.style.transition = "none";
  });
  card.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    dx = e.clientX - sx; dy = (e.clientY - sy) * 0.4;
    const rot = dx / 14, scale = Math.max(0.94, 1 - Math.abs(dx) / 1400);
    card.style.transform = `translate(${dx}px,${dy}px) rotate(${rot}deg) scale(${scale})`;
    show(like, dx / 90); show(nope, -dx / 90);
  });
  const up = () => {
    if (!dragging) return;
    dragging = false;
    if (dx > 110) doSwipe(profile, true, card);
    else if (dx < -110) doSwipe(profile, false, card);
    else {
      // spring back under threshold
      card.style.transition = "transform .38s cubic-bezier(.2,1.6,.4,1)";
      card.style.transform = "";
      like.style.opacity = nope.style.opacity = 0;
      setTimeout(() => (card.style.transition = ""), 400);
    }
    dx = dy = 0;
  };
  card.addEventListener("pointerup", up);
  card.addEventListener("pointercancel", up);
}
async function doSwipe(profile, liked, card, superLike = false) {
  const dir = liked ? 1 : -1;
  card.style.transition = "transform .4s cubic-bezier(.3,.7,.4,1), opacity .4s";
  card.style.transform =
    `translate(${dir * 460}px,${superLike ? -160 : -60}px) rotate(${dir * 28}deg) scale(.9)`;
  card.style.opacity = "0";
  const { status, data } = await post("/api/swipe", { target_id: profile.id, liked });
  if (status === 402) {
    toast("Daily like limit reached — Go Premium! ⭐");
    showPremium();
    renderStack();
    return;
  }
  if (!data.ok) { toast(data.error || "error"); renderStack(); return; }
  STACK.shift();
  if (superLike) toast(`⭐ Super liked ${profile.name}!`);
  else if (liked) toast(`💚 Liked ${profile.name}`);
  setTimeout(renderStack, 160);
  if (data.matched) setTimeout(() => showMatchModal(profile, data.match_id), 350);
}
$("btnLike").onclick = () => { const c = $("stack").lastChild; if (STACK[0] && c && c.classList.contains("scard")) doSwipe(STACK[0], true, c); };
$("btnNope").onclick = () => { const c = $("stack").lastChild; if (STACK[0] && c && c.classList.contains("scard")) doSwipe(STACK[0], false, c); };
$("btnSuper").onclick = () => {
  const c = $("stack").lastChild;
  if (STACK[0] && c && c.classList.contains("scard")) {
    const st = c.querySelector(".stamp.super");
    st.style.opacity = 1; st.style.transform = "translateX(-50%) scale(1.1)";
    doSwipe(STACK[0], true, c, true);
  }
};

function confettiBurst(container) {
  const colors = ["#ff4d6d", "#8b5cf6", "#fb923c", "#34d399", "#fbbf24", "#ffffff"];
  for (let i = 0; i < 46; i++) {
    const c = document.createElement("div");
    c.className = "confetti";
    c.style.left = Math.random() * 100 + "%";
    c.style.background = colors[i % colors.length];
    c.style.animationDuration = 2.2 + Math.random() * 1.6 + "s";
    c.style.animationDelay = Math.random() * 0.5 + "s";
    if (Math.random() > 0.6) c.style.borderRadius = "50%";
    container.appendChild(c);
    setTimeout(() => c.remove(), 4500);
  }
}
function showMatchModal(profile, match_id) {
  const box = $("modalBox");
  box.innerHTML = `<h2>It's a Match! 💘</h2>
    <p class="muted">You and <b style="color:#fff">${esc(profile.name)}</b> liked each other.</p>
    <div class="pair">${avatarHTML(ME, 76)}${avatarHTML(profile, 76)}</div>
    <button class="btn" id="mChat">Send message 👋</button>
    <button class="btn ghost" id="mClose">Keep swiping</button>`;
  $("modal").classList.add("on");
  confettiBurst(box);
  $("mChat").onclick = () => { $("modal").classList.remove("on"); openChat(match_id); };
  $("mClose").onclick = () => $("modal").classList.remove("on");
}

/* ---------------------------------------------------------- matches */
async function loadMatches() {
  const box = $("matchList");
  box.innerHTML = `<div class="skelrow"><div class="skel a"></div><div class="skel b"></div></div>
    <div class="skelrow"><div class="skel a"></div><div class="skel b"></div></div>
    <div class="skelrow"><div class="skel a"></div><div class="skel b"></div></div>`;
  const { data } = await api("/api/matches");
  const ms = data.matches || [];
  let html = "";
  if (ME.is_premium) {
    const lb = await api("/api/liked_by");
    const likers = lb.data.profiles || [];
    if (likers.length) {
      html += `<div class="muted" style="margin:6px 0">👀 Liked you (${likers.length}) — Premium</div>`;
      html += likers.map((p) =>
        `<div class="mrow">${avatarHTML(p)}<div><span class="nm">${esc(p.name)}, ${p.age}</span>
         <span class="pill">LIKES YOU</span></div></div>`).join("");
    }
  }
  html += ms.length ? ms.map((m) => `
    <div class="mrow" data-m="${m.match_id}">
      ${avatarHTML(m.user)}
      <div><div class="nm">${esc(m.user.name)}, ${m.user.age}</div>
      <div class="lm">${m.last_message ? esc(m.last_message.text) : "Say hello 👋"}</div></div>
    </div>`).join("")
    : `<div class="empty"><span class="big">💌</span><b>No matches yet</b><br>
       Your likes are out there — keep swiping and someone great will match back.
       <div class="cta"><button class="btn" onclick="loadDiscover();showView('v-discover')">
       💘 Start swiping</button></div></div>`;
  box.innerHTML = html;
  box.querySelectorAll(".mrow[data-m]").forEach((r) =>
    (r.onclick = () => openChat(+r.dataset.m)));
}

/* ---------------------------------------------------------- chat */
async function openChat(match_id) {
  const { data } = await api("/api/matches");
  const m = (data.matches || []).find((x) => x.match_id === match_id);
  if (!m) return;
  CHAT = { match_id, other: m.user };
  lastSignalId = 0;
  $("chatName").textContent = m.user.name;
  $("chatAge").textContent = m.user.age + " years old";
  $("chatAvatar").outerHTML = avatarHTML(m.user).replace('class="avatar"',
    'id="chatAvatar" class="avatar"');
  showView("v-chat");
  $("msgs").innerHTML = `<div class="typing"><span></span><span></span><span></span></div>`;
  setTimeout(loadMessages, 700);
  clearInterval(msgTimer); clearInterval(sigTimer);
  msgTimer = setInterval(loadMessages, 3000);
  sigTimer = setInterval(pollSignals, 2000);
}
$("chatBack").onclick = () => {
  clearInterval(msgTimer); clearInterval(sigTimer);
  CHAT = null; loadMatches(); showView("v-matches");
};
function fmtTime(ts) {
  const d = new Date(ts * 1000);
  let h = d.getHours(), m = String(d.getMinutes()).padStart(2, "0");
  const ap = h >= 12 ? "PM" : "AM";
  h = h % 12 || 12;
  return `${h}:${m} ${ap}`;
}
function dayLabel(ts) {
  const d = new Date(ts * 1000), t = new Date();
  const day = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const today = new Date(t.getFullYear(), t.getMonth(), t.getDate());
  const diff = Math.round((today - day) / 86400000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Yesterday";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}
function renderMessage(m) {
  const mine = m.sender_id === ME.id;
  const cls = mine ? "me" : "them";
  const ts = `<span class="ts">${fmtTime(m.ts)}</span>`;
  const kind = m.kind || "text";
  if (kind === "gift") {
    let ex = {};
    try { ex = JSON.parse(m.extra || "{}"); } catch (e) {}
    const who = mine ? "You" : esc(CHAT.other.name);
    return `<div class="bubble giftmsg"><span class="big">${esc(ex.emoji || "🎁")}</span>
      <b>${who} sent ${mine ? "them" : "you"} a ${esc(ex.name || "gift")} ${esc(ex.emoji || "")}</b>${ts}</div>`;
  }
  if (kind === "game_invite") {
    let ex = {};
    try { ex = JSON.parse(m.extra || "{}"); } catch (e) {}
    const gname = ex.game === "rps" ? "Rock-Paper-Scissors" : "Tic-Tac-Toe";
    const who = mine ? "You" : esc(CHAT.other.name);
    return `<div class="bubble inviteMsg"><span class="big">🎮</span>
      <b>${who} invited ${mine ? "them" : "you"} to play ${gname}</b>
      ${mine ? "" : `<button class="btn small" onclick="openGame(${ex.session_id || 0})">Join ▶</button>`}
      ${ts}</div>`;
  }
  return `<div class="bubble ${cls}">${esc(m.text)}${ts}</div>`;
}
async function loadMessages() {
  if (!CHAT) return;
  const { data } = await api(`/api/messages?match_id=${CHAT.match_id}`);
  const box = $("msgs");
  const msgs = data.messages || [];
  let html = "", lastDay = "";
  for (const m of msgs) {
    const dl = dayLabel(m.ts);
    if (dl !== lastDay) { html += `<div class="daydiv">${dl}</div>`; lastDay = dl; }
    html += renderMessage(m);
  }
  box.innerHTML = html;
  box.scrollTop = box.scrollHeight;
}
async function sendMsg() {
  const t = $("msgInput").value.trim();
  if (!t || !CHAT) return;
  $("msgInput").value = "";
  await post("/api/message", { match_id: CHAT.match_id, text: t });
  loadMessages();
}
$("btnSend").onclick = sendMsg;
$("msgInput").addEventListener("keydown", (e) => { if (e.key === "Enter") sendMsg(); });

/* ---------------------------------------------------------- video call */
const STUN = { iceServers: [{ urls: "stun:stun.l.google.com:19302" }] };
let pc = null, localStream = null, inCall = false, callRole = null;

function callLog(s) { $("callStatus").textContent = s; }

async function postSignal(kind, payload) {
  if (!CHAT) return;
  await post("/api/call/signal", {
    match_id: CHAT.match_id, kind, payload: payload || "",
  });
}

async function startCall() {
  if (inCall || !CHAT) return;
  try {
    localStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
  } catch (e) { toast("Camera/mic blocked — allow access to call"); return; }
  inCall = true; callRole = "caller";
  $("callOverlay").classList.add("on");
  $("localVideo").srcObject = localStream;
  callLog("Calling " + CHAT.other.name + "…");
  pc = new RTCPeerConnection(STUN);
  localStream.getTracks().forEach((t) => pc.addTrack(t, localStream));
  wirePC();
  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  await postSignal("ring", CHAT.other.name);
  await postSignal("offer", JSON.stringify(offer));
}
$("btnCall").onclick = startCall;

function wirePC() {
  pc.onicecandidate = (e) => {
    if (e.candidate) postSignal("ice", JSON.stringify(e.candidate));
  };
  pc.ontrack = (e) => {
    $("remoteVideo").srcObject = e.streams[0];
    callLog("Connected with " + (CHAT ? CHAT.other.name : ""));
  };
  pc.onconnectionstatechange = () => {
    if (["disconnected", "failed", "closed"].includes(pc.connectionState)) endCall(false);
  };
}

async function acceptCall(offerPayload) {
  try {
    localStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
  } catch (e) { toast("Camera/mic blocked — allow access to call"); return; }
  inCall = true; callRole = "callee";
  $("modal").classList.remove("on");
  $("callOverlay").classList.add("on");
  $("localVideo").srcObject = localStream;
  callLog("Connecting…");
  pc = new RTCPeerConnection(STUN);
  localStream.getTracks().forEach((t) => pc.addTrack(t, localStream));
  wirePC();
  await pc.setRemoteDescription(new RTCSessionDescription(JSON.parse(offerPayload)));
  const answer = await pc.createAnswer();
  await pc.setLocalDescription(answer);
  await postSignal("answer", JSON.stringify(answer));
}

async function endCall(notify = true) {
  if (notify && CHAT) { try { await postSignal("hangup", ""); } catch (e) {} }
  try { pc && pc.close(); } catch (e) {}
  try { localStream && localStream.getTracks().forEach((t) => t.stop()); } catch (e) {}
  pc = null; localStream = null; inCall = false; callRole = null;
  window._incomingShown = false; window._pendingOffer = null;
  $("remoteVideo").srcObject = null; $("localVideo").srcObject = null;
  $("callOverlay").classList.remove("on");
}
$("btnHangup").onclick = () => endCall(true);
$("btnMute").onclick = (e) => {
  if (!localStream) return;
  const t = localStream.getAudioTracks()[0];
  t.enabled = !t.enabled;
  e.currentTarget.classList.toggle("off", !t.enabled);
};
$("btnCam").onclick = (e) => {
  if (!localStream) return;
  const t = localStream.getVideoTracks()[0];
  t.enabled = !t.enabled;
  e.currentTarget.classList.toggle("off", !t.enabled);
};

async function pollSignals() {
  if (!CHAT) return;
  const { data } = await api(
    `/api/call/signal?match_id=${CHAT.match_id}&since=${lastSignalId}`);
  for (const s of data.signals || []) {
    lastSignalId = Math.max(lastSignalId, s.id);
    if (s.sender_id === ME.id) continue;
    if (s.kind === "ring" && !inCall) {
      showIncomingCall();
    } else if (s.kind === "offer" && !inCall) {
      window._pendingOffer = s.payload; // stored until user accepts
    } else if (s.kind === "answer" && inCall && callRole === "caller" && pc) {
      await pc.setRemoteDescription(new RTCSessionDescription(JSON.parse(s.payload)));
    } else if (s.kind === "ice" && inCall && pc) {
      try { await pc.addIceCandidate(new RTCIceCandidate(JSON.parse(s.payload))); }
      catch (e) {}
    } else if (s.kind === "hangup" && inCall) {
      endCall(false); toast("Call ended");
    }
  }
}

function showIncomingCall() {
  if (inCall || window._incomingShown) return;
  window._incomingShown = true;
  $("modalBox").innerHTML = `<h2>📹 Incoming call</h2>
    <div class="pair">${avatarHTML(CHAT.other, 70)}</div>
    <p><b>${esc(CHAT.other.name)}</b> is calling you</p>
    <button class="btn" id="cAccept">Accept ✅</button>
    <button class="btn ghost" id="cDecline">Decline</button>`;
  $("modal").classList.add("on");
  $("cAccept").onclick = async () => {
    window._incomingShown = false;
    // offer usually arrives in the same poll batch as ring; wait briefly if not yet here
    for (let i = 0; i < 10 && !window._pendingOffer; i++)
      await new Promise((r) => setTimeout(r, 400));
    if (!window._pendingOffer) { toast("Offer not received — ask them to call again"); $("modal").classList.remove("on"); return; }
    acceptCall(window._pendingOffer);
  };
  $("cDecline").onclick = async () => {
    window._incomingShown = false;
    $("modal").classList.remove("on");
    await postSignal("hangup", "declined");
  };
}

/* ---------------------------------------------------------- games */
let GAME = null, gameTimer = null; // {session_id, game}
const GAME_NAMES = { tictactoe: "Tic-Tac-Toe", rps: "Rock-Paper-Scissors" };

$("btnGame").onclick = () => {
  if (!CHAT) return;
  $("modalBox").innerHTML = `<h2>🎮 Play a game</h2>
    <p class="muted">Challenge <b style="color:#fff">${esc(CHAT.other.name)}</b></p>
    <button class="btn" data-g="tictactoe">⭕ Tic-Tac-Toe</button>
    <button class="btn" data-g="rps">✊ Rock-Paper-Scissors</button>
    <button class="btn ghost" id="gCancel">Cancel</button>`;
  $("modal").classList.add("on");
  $("gCancel").onclick = () => $("modal").classList.remove("on");
  $("modalBox").querySelectorAll("[data-g]").forEach((b) => {
    b.onclick = () => startGame(b.dataset.g);
  });
};

async function startGame(game) {
  $("modal").classList.remove("on");
  const { data } = await post("/api/game/start", { match_id: CHAT.match_id, game });
  if (!data.ok) { toast(data.error || "Could not start game"); return; }
  // notify opponent with a special message
  await post("/api/message", {
    match_id: CHAT.match_id,
    text: `invited you to play ${GAME_NAMES[game]} 🎮`,
    kind: "game_invite",
    extra: JSON.stringify({ session_id: data.session.session_id, game }),
  });
  loadMessages();
  openGame(data.session.session_id);
}

async function openGame(session_id) {
  if (!session_id) return;
  const { data } = await api(`/api/game/state?session_id=${session_id}`);
  if (!data.ok) { toast(data.error || "Game not found"); return; }
  GAME = data.session;
  $("gameTitle").textContent = "🎮 " + (GAME_NAMES[GAME.game] || "Game");
  $("gameOverlay").classList.add("on");
  renderGame();
  clearInterval(gameTimer);
  gameTimer = setInterval(refreshGame, 1500);
}
$("gameClose").onclick = () => {
  clearInterval(gameTimer); GAME = null;
  $("gameOverlay").classList.remove("on");
};
async function refreshGame() {
  if (!GAME) return;
  const { data } = await api(`/api/game/state?session_id=${GAME.session_id}`);
  if (data.ok) { GAME = data.session; renderGame(); }
}

function renderGame() {
  const body = $("gameBody");
  const st = GAME.state, meA = GAME.you_are === "a";
  const myMark = GAME.game === "tictactoe" ? (meA ? "X" : "O") : null;
  let html = "";
  if (GAME.game === "tictactoe") {
    const turnMine = st.turn === ME.id;
    const cells = st.board.map((c, i) =>
      `<button data-cell="${i}" ${c || GAME.status === "finished" ? "disabled" : ""}
        class="${c === "X" ? "x" : c === "O" ? "o" : ""}">${c || ""}</button>`).join("");
    html = `<div class="scoreboard"><span class="me">You (${myMark})</span><span>·</span>
      <span class="op">${esc(CHAT ? CHAT.other.name : "Opponent")}</span></div>
      <div class="ttt">${cells}</div>
      <div class="turnNote">${GAME.status === "finished" ? "" :
        turnMine ? "Your move 👆" : "Waiting for opponent…"}</div>`;
  } else {
    const mine = st.choices[String(ME.id)];
    const emo = { rock: "✊", paper: "✋", scissors: "✌️" };
    html = `<div class="scoreboard"><span class="me">You ${st.score.a}</span><span>·</span>
      <span class="muted">Round ${st.round}</span><span>·</span>
      <span class="op">${st.score.b} ${esc(CHAT ? CHAT.other.name : "Opponent")}</span></div>`;
    if (mine) {
      html += `<div class="rpsreveal">${emo[mine]}</div>
        <div class="turnNote">You chose ${mine} — waiting for opponent…</div>`;
    } else if (GAME.status !== "finished") {
      html += `<div class="rpsbtns">
        <button data-rps="rock">✊</button><button data-rps="paper">✋</button>
        <button data-rps="scissors">✌️</button></div>
        <div class="turnNote">First to ${3} wins 🏆</div>`;
    }
  }
  if (GAME.status === "finished") {
    const won = GAME.winner_id === ME.id;
    const draw = GAME.winner_id == null;
    html += `<div class="winnerBanner">${draw ? "It's a draw! 🤝" :
      won ? "You won! 🎉" : `${esc(CHAT ? CHAT.other.name : "Opponent")} won`}</div>
      <button class="btn" id="gameDone" style="max-width:260px">Done</button>`;
  }
  body.innerHTML = html;
  body.querySelectorAll("[data-cell]").forEach((b) => {
    b.onclick = () => gameMove({ cell: +b.dataset.cell });
  });
  body.querySelectorAll("[data-rps]").forEach((b) => {
    b.onclick = () => gameMove({ choice: b.dataset.rps });
  });
  const done = $("gameDone");
  if (done) done.onclick = () => $("gameClose").click();
}

async function gameMove(move) {
  const { data } = await post("/api/game/move",
    { session_id: GAME.session_id, move });
  if (!data.ok) { toast(data.error || "Illegal move"); return; }
  GAME = data.session;
  renderGame();
}

/* ---------------------------------------------------------- gifts */
let GIFTS_CACHE = null, WALLET_CACHE = 0;
async function giftCatalog() {
  if (!GIFTS_CACHE) GIFTS_CACHE = (await api("/api/gifts")).data.gifts || [];
  return GIFTS_CACHE;
}
async function walletCoins() {
  WALLET_CACHE = (await api("/api/wallet")).data.coins || 0;
  return WALLET_CACHE;
}
$("btnGift").onclick = async () => {
  if (!CHAT) return;
  const [gifts, coins] = [await giftCatalog(), await walletCoins()];
  const box = $("modalBox");
  const grid = gifts.map((g) =>
    `<div class="gift" data-g="${g.id}"><span class="em">${g.emoji}</span>
     <span class="nm">${esc(g.name)}</span><span class="pr">🪙 ${g.price}</span></div>`).join("");
  box.innerHTML = `<h2>🎁 Send a gift</h2>
    <div class="coinbar"><span>🪙 <b id="coinBal">${coins}</b> coins</span>
      <button class="btn small" id="buyCoins" style="margin:0">Buy coins</button></div>
    <div class="giftgrid">${grid}</div>
    <button class="btn ghost" id="giftCancel">Cancel</button>`;
  $("modal").classList.add("on");
  $("giftCancel").onclick = () => $("modal").classList.remove("on");
  $("buyCoins").onclick = showWallet;
  box.querySelectorAll(".gift").forEach((el) => {
    el.onclick = () => sendGift(el.dataset.g, el);
  });
};
async function sendGift(gift_id, el) {
  const { status, data } = await post("/api/gift/send",
    { match_id: CHAT.match_id, gift_id });
  if (status === 402) {
    el.classList.add("shake");
    setTimeout(() => el.classList.remove("shake"), 450);
    toast("Not enough coins — buy more! 🪙");
    showWallet();
    return;
  }
  if (!data.ok) { toast(data.error || "Could not send gift"); return; }
  $("modal").classList.remove("on");
  WALLET_CACHE = data.coins_left;
  toast("Gift sent! 🎁");
  loadMessages();
}
async function showWallet() {
  const coins = await walletCoins();
  let pay = "";
  try {
    const d = await (await fetch("/api/paylink")).json();
    if (d.link) pay = `<a class="btn" href="${esc(d.link)}" target="_blank" rel="noopener">
      💳 Buy coins</a><div class="muted" style="margin-top:8px">After payment the operator
      tops up your wallet.</div>`;
  } catch (e) { /* offline / not configured */ }
  if (!pay) pay = `<div class="inviteCard">🪙 <b>Coin top-up</b><br>
    <span class="muted">Contact the admin to buy coins — top-ups are added manually.</span></div>`;
  $("modalBox").innerHTML = `<h2>🪙 Wallet</h2>
    <div class="coinbar" style="margin-bottom:12px"><span>Balance</span><b>${coins} coins</b></div>
    ${pay}
    <button class="btn ghost" id="wBack">‹ Back</button>`;
  $("modal").classList.add("on");
  $("wBack").onclick = () => $("btnGift").click();
}

/* ---------------------------------------------------------- profile */
let CAR_IDX = 0;
function carouselPhotos() {
  return ME.photos && ME.photos.length ? ME.photos : [];
}
function renderCarousel() {
  const box = $("pcar");
  const photos = carouselPhotos();
  CAR_IDX = Math.min(CAR_IDX, Math.max(0, photos.length - 1));
  const media = photos.length
    ? `<div class="slide"><img src="${esc(photos[CAR_IDX])}" draggable="false"></div>`
    : `<div class="slide">👤</div>`;
  const dots = photos.length > 1
    ? `<div class="dots">${photos.map((_, i) =>
        `<i class="${i === CAR_IDX ? "on" : ""}"></i>`).join("")}</div>` : "";
  box.innerHTML = `${media}<div class="scrim"></div>
    <div class="who"><b>${esc(ME.name)}</b> <span>${ME.age == null ? "" : ME.age}</span></div>
    ${dots}`;
  // swipe through own photos
  let sx = 0, dragging = false;
  box.onpointerdown = (e) => { dragging = true; sx = e.clientX; };
  box.onpointermove = () => {};
  box.onpointerup = (e) => {
    if (!dragging) return;
    dragging = false;
    const dx = e.clientX - sx;
    if (dx < -40 && CAR_IDX < photos.length - 1) { CAR_IDX++; renderCarousel(); }
    else if (dx > 40 && CAR_IDX > 0) { CAR_IDX--; renderCarousel(); }
  };
}
function renderStrip() {
  const s = $("pstrip");
  s.innerHTML = "";
  (ME.photos || []).forEach((url) => {
    const d = document.createElement("div");
    d.className = "thumb";
    d.innerHTML = `<img src="${esc(url)}"><button aria-label="Delete">✕</button>`;
    d.querySelector("button").onclick = async (e) => {
      e.stopPropagation();
      const fn = url.split("/").pop();
      const r = await api("/api/photo", {
        method: "DELETE", body: JSON.stringify({ filename: fn }),
      });
      if (r.data.ok) {
        ME.photos = r.data.photos; renderCarousel(); renderStrip();
        toast("Photo removed");
      }
    };
    s.appendChild(d);
  });
  if ((ME.photos || []).length < 6) {
    const add = document.createElement("div");
    add.className = "thumb add";
    add.textContent = "＋";
    add.onclick = () => $("photoInput").click();
    s.appendChild(add);
  }
}
async function loadProfile() {
  const { data } = await api("/api/me");
  ME = data.user;
  $("pfName").value = ME.name;
  $("pfBio").value = ME.bio;
  $("pfInterests").value = ME.interests;
  $("pfGender").value = ME.gender;
  $("pfLooking").value = ME.looking_for;
  $("pfDiscoverable").checked = ME.discoverable !== false;
  CAR_IDX = 0;
  renderCarousel();
  renderStrip();
  const box = $("premBox");
  if (ME.is_premium) {
    const until = ME.premium_until
      ? new Date(ME.premium_until * 1000).toLocaleDateString() : "";
    box.innerHTML = `⭐ <b>Premium active</b> ${until ? "until " + esc(until) : ""}`;
  } else {
    box.innerHTML = `You are on the <b>free</b> plan.<br>
      <button class="btn small" id="goPrem2">⭐ Go Premium</button>`;
    $("goPrem2").onclick = showPremium;
  }
}
$("photoInput").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("photo", f);
  const r = await fetch("/api/upload", { method: "POST", body: fd });
  const data = await r.json();
  if (!data.ok) { $("pfErr").textContent = data.error; return; }
  ME.photos = data.photos; renderCarousel(); renderStrip(); toast("Photo added 📸");
  e.target.value = "";
});
$("btnSaveProfile").onclick = async () => {
  $("pfErr").textContent = "";
  const { data } = await post("/api/profile", {
    name: $("pfName").value.trim(), bio: $("pfBio").value,
    interests: $("pfInterests").value, gender: $("pfGender").value,
    looking_for: $("pfLooking").value,
    discoverable: $("pfDiscoverable").checked,
  });
  if (!data.ok) { $("pfErr").textContent = data.error; return; }
  ME = data.user; toast("Profile saved ✅");
};
$("btnLogout").onclick = async () => {
  await post("/api/logout", {});
  location.reload();
};

/* ---------------------------------------------------------- premium */
function showPremium() {
  const box = $("payArea");
  box.innerHTML = `<div class="center muted">Checking payment setup…</div>`;
  showView("v-premium");
  fetch("/api/paylink").then((r) => r.json()).then((d) => {
    if (d.link) {
      box.innerHTML = `<a class="btn" href="${esc(d.link)}" target="_blank" rel="noopener">
        💳 Pay & activate Premium</a>
        <div class="muted center" style="margin-top:8px">After payment, the operator
        activates your Premium (usually within hours).</div>`;
    } else {
      box.innerHTML = `<div class="inviteCard">💳 <b>Payment setup pending</b><br>
        <span class="muted">Contact the admin to activate Premium.</span></div>`;
    }
  }).catch(() => {
    box.innerHTML = `<div class="inviteCard">💳 <b>Payment setup pending</b></div>`;
  });
}
$("premBack").onclick = () => { loadProfile(); showView("v-profile"); };

/* ---------------------------------------------------------- invite */
async function loadInvite() {
  const { data } = await api("/api/referrals");
  $("inviteLink").textContent = data.invite_link || "—";
  $("statInvites").textContent = data.referrals_count || 0;
  $("statDays").textContent = data.premium_days_earned || 0;
}
$("btnCopyLink").onclick = async () => {
  const link = $("inviteLink").textContent;
  try { await navigator.clipboard.writeText(link); toast("Link copied 📋"); }
  catch (e) {
    const ta = document.createElement("textarea");
    ta.value = link; document.body.appendChild(ta); ta.select();
    document.execCommand("copy"); ta.remove(); toast("Link copied 📋");
  }
};
$("btnShare").onclick = async () => {
  const link = $("inviteLink").textContent;
  if (navigator.share) {
    try { await navigator.share({ title: "DateSwipe", text: "Join me on DateSwipe 💘", url: link }); }
    catch (e) {}
  } else { $("btnCopyLink").click(); }
};

/* ---------------------------------------------------------- ads */
let ADS = null;
async function initAds() {
  try {
    const { data } = await api("/api/ads/config");
    if (!data.enabled || !data.client_id) return;
    ADS = data;
    const s = document.createElement("script");
    s.async = true;
    s.src = "https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client="
      + encodeURIComponent(data.client_id);
    s.crossOrigin = "anonymous";
    document.head.appendChild(s);
    const slots = data.slots || {};
    const map = { adDiscover: slots.discover, adMatches: slots.matches, adChat: slots.chat };
    for (const [elId, slot] of Object.entries(map)) {
      if (!slot) continue;
      const el = $(elId);
      if (!el) continue;
      el.innerHTML = `<span class="adlabel">Advertisement</span>
        <ins class="adsbygoogle" style="display:block"
             data-ad-client="${esc(data.client_id)}" data-ad-slot="${esc(slot)}"
             data-ad-format="auto" data-full-width-responsive="true"></ins>`;
      el.classList.add("live");
    }
    s.onload = () => {
      try {
        document.querySelectorAll(".adslot.live ins.adsbygoogle").forEach(() => {
          (window.adsbygoogle = window.adsbygoogle || []).push({});
        });
      } catch (e) {}
    };
  } catch (e) { /* ads disabled or unreachable — app works without them */ }
}

/* ---------------------------------------------------------- privacy */
function showPrivacy(from) {
  window._privacyFrom = from || (ME ? "v-profile" : "v-auth");
  showView("v-privacy");
}
$("linkPrivacy1").onclick = (e) => { e.preventDefault(); showPrivacy("v-auth"); };
$("linkPrivacy2").onclick = (e) => { e.preventDefault(); showPrivacy("v-profile"); };
$("privacyBack").onclick = () => showView(window._privacyFrom || "v-profile");

/* ---------------------------------------------------------- init */
(async function init() {
  initAds();
  // referral autofill from ?ref=
  const ref = new URLSearchParams(location.search).get("ref");
  if (ref) {
    $("tabSignup").click();
    $("suRef").value = ref.toUpperCase();
  }
  if ("serviceWorker" in navigator) {
    try { await navigator.serviceWorker.register("/sw.js"); } catch (e) {}
  }
  try {
    const { data } = await api("/api/me");
    ME = data.user; showMain();
  } catch (e) { showAuth(); }
})();
