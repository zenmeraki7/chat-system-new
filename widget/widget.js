(function () {
  "use strict";

  const cfg = window.ChatWidgetConfig || {};
  const API_KEY = cfg.apiKey || "";
  const BASE_URL = (cfg.baseUrl || "http://localhost:8000").replace(/\/$/, "");
  const WS_URL = BASE_URL.replace(/^http/, "ws");
  const PRIMARY = cfg.primaryColor || "#6366f1";
  const TITLE = cfg.title || "Chat with us";
  const STORAGE_KEY = "cs_visitor_id_" + API_KEY;
  const MSGS_KEY = "cs_messages_" + API_KEY;

  // ── Visitor ID (persisted in localStorage) ──────────────────────────────────
  function getVisitorId() {
    let id = localStorage.getItem(STORAGE_KEY);
    if (!id) {
      id = "v_" + Math.random().toString(36).slice(2) + Date.now().toString(36);
      localStorage.setItem(STORAGE_KEY, id);
    }
    return id;
  }

  const VISITOR_ID = getVisitorId();
  let socket = null;
  let isOpen = false;
  let messages = [];

  // ── Inject CSS ────────────────────────────────────────────────────────────────
  const style = document.createElement("style");
  style.textContent = `
    #cs-widget-btn {
      position: fixed; bottom: 28px; right: 28px; z-index: 99999;
      width: 60px; height: 60px; border-radius: 50%;
      background: ${PRIMARY}; border: none; cursor: pointer;
      box-shadow: 0 8px 25px rgba(0,0,0,0.25);
      display: flex; align-items: center; justify-content: center;
      transition: transform 0.2s, box-shadow 0.2s;
    }
    #cs-widget-btn:hover { transform: scale(1.08); box-shadow: 0 12px 30px rgba(0,0,0,0.3); }
    #cs-widget-btn svg { width: 28px; height: 28px; fill: #fff; }

    #cs-chat-window {
      position: fixed; bottom: 100px; right: 28px; z-index: 99998;
      width: 370px; height: 540px; border-radius: 20px;
      background: #fff; box-shadow: 0 20px 60px rgba(0,0,0,0.18);
      display: flex; flex-direction: column; overflow: hidden;
      transform: scale(0.85) translateY(20px); opacity: 0;
      transform-origin: bottom right;
      transition: transform 0.25s cubic-bezier(0.34,1.56,0.64,1), opacity 0.2s;
      pointer-events: none;
    }
    #cs-chat-window.open {
      transform: scale(1) translateY(0); opacity: 1; pointer-events: all;
    }

    #cs-header {
      background: ${PRIMARY}; color: #fff;
      padding: 18px 20px; display: flex; align-items: center; gap: 12px;
      flex-shrink: 0;
    }
    #cs-header-avatar {
      width: 40px; height: 40px; border-radius: 50%; background: rgba(255,255,255,0.25);
      display: flex; align-items: center; justify-content: center; font-size: 18px;
    }
    #cs-header-info h3 { margin: 0; font-size: 15px; font-weight: 600; font-family: sans-serif; }
    #cs-header-info p { margin: 2px 0 0; font-size: 12px; opacity: 0.85; font-family: sans-serif; }
    #cs-status-dot { width: 8px; height: 8px; border-radius: 50%; background: #4ade80; display: inline-block; margin-right: 4px; }

    #cs-messages {
      flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 10px;
      background: #f8f9ff;
    }
    #cs-messages::-webkit-scrollbar { width: 4px; }
    #cs-messages::-webkit-scrollbar-thumb { background: #ddd; border-radius: 4px; }

    .cs-msg {
      max-width: 82%; padding: 10px 14px; border-radius: 16px;
      font-size: 14px; line-height: 1.5; font-family: sans-serif;
      animation: csFadeIn 0.2s ease;
    }
    @keyframes csFadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
    .cs-msg.user {
      align-self: flex-end; background: ${PRIMARY}; color: #fff;
      border-bottom-right-radius: 4px;
    }
    .cs-msg.assistant {
      align-self: flex-start; background: #fff; color: #1e1e2e;
      border-bottom-left-radius: 4px; box-shadow: 0 2px 8px rgba(0,0,0,0.07);
    }
    .cs-msg-time { font-size: 10px; opacity: 0.6; margin-top: 4px; display: block; }

    #cs-typing {
      align-self: flex-start; background: #fff; padding: 10px 16px;
      border-radius: 16px; border-bottom-left-radius: 4px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.07); display: none;
    }
    #cs-typing span {
      display: inline-block; width: 7px; height: 7px; margin: 0 2px;
      background: ${PRIMARY}; border-radius: 50%; animation: csTyping 1.2s infinite;
    }
    #cs-typing span:nth-child(2) { animation-delay: 0.2s; }
    #cs-typing span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes csTyping {
      0%, 80%, 100% { transform: translateY(0); opacity: 0.4; }
      40% { transform: translateY(-6px); opacity: 1; }
    }

    #cs-input-area {
      padding: 12px 16px; border-top: 1px solid #f0f0f0; display: flex; gap: 8px;
      background: #fff; flex-shrink: 0;
    }
    #cs-input {
      flex: 1; border: 1.5px solid #e5e7eb; border-radius: 12px;
      padding: 10px 14px; font-size: 14px; font-family: sans-serif;
      outline: none; resize: none; transition: border-color 0.2s;
      max-height: 120px; min-height: 42px;
    }
    #cs-input:focus { border-color: ${PRIMARY}; }
    #cs-send-btn {
      width: 42px; height: 42px; border-radius: 12px; background: ${PRIMARY};
      border: none; cursor: pointer; display: flex; align-items: center;
      justify-content: center; flex-shrink: 0; transition: opacity 0.2s;
    }
    #cs-send-btn:hover { opacity: 0.85; }
    #cs-send-btn svg { width: 18px; height: 18px; fill: #fff; }

    #cs-empty {
      text-align: center; padding: 40px 20px; font-family: sans-serif;
    }
    #cs-empty p { color: #9ca3af; font-size: 14px; margin: 8px 0 0; }
    #cs-empty .cs-wave { font-size: 40px; }

    @media (max-width: 420px) {
      #cs-chat-window { width: calc(100vw - 20px); right: 10px; bottom: 90px; height: 70vh; }
      #cs-widget-btn { bottom: 16px; right: 16px; }
    }
  `;
  document.head.appendChild(style);

  // ── Build HTML ────────────────────────────────────────────────────────────────
  const btn = document.createElement("button");
  btn.id = "cs-widget-btn";
  btn.setAttribute("aria-label", "Open chat");
  btn.innerHTML = `<svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>`;

  const win = document.createElement("div");
  win.id = "cs-chat-window";
  win.setAttribute("role", "dialog");
  win.setAttribute("aria-label", TITLE);
  win.innerHTML = `
    <div id="cs-header">
      <div id="cs-header-avatar">💬</div>
      <div id="cs-header-info">
        <h3>${TITLE}</h3>
        <p><span id="cs-status-dot" class="cs-status-dot"></span>Online — AI-powered</p>
      </div>
    </div>
    <div id="cs-messages">
      <div id="cs-empty">
        <div class="cs-wave">👋</div>
        <p>Hi there! How can we help you today?</p>
      </div>
      <div id="cs-typing"><span></span><span></span><span></span></div>
    </div>
    <div id="cs-input-area">
      <textarea id="cs-input" placeholder="Type a message..." rows="1" aria-label="Message input"></textarea>
      <button id="cs-send-btn" aria-label="Send message">
        <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
      </button>
    </div>
  `;

  document.body.appendChild(btn);
  document.body.appendChild(win);

  // ── Helpers ───────────────────────────────────────────────────────────────────
  const msgsEl = document.getElementById("cs-messages");
  const inputEl = document.getElementById("cs-input");
  const sendBtn = document.getElementById("cs-send-btn");
  const typingEl = document.getElementById("cs-typing");
  const emptyEl = document.getElementById("cs-empty");

  function formatTime(iso) {
    const d = new Date(iso || Date.now());
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function appendMessage(role, content, time) {
    if (emptyEl) emptyEl.style.display = "none";
    const div = document.createElement("div");
    div.className = "cs-msg " + role;
    div.innerHTML = `${content}<span class="cs-msg-time">${formatTime(time)}</span>`;
    msgsEl.insertBefore(div, typingEl);
    msgsEl.scrollTop = msgsEl.scrollHeight;
  }

  function showTyping(show) {
    typingEl.style.display = show ? "flex" : "none";
    if (show) msgsEl.scrollTop = msgsEl.scrollHeight;
  }

  function saveMessages() {
    try { localStorage.setItem(MSGS_KEY, JSON.stringify(messages)); } catch (e) {}
  }

  function loadLocalMessages() {
    try { return JSON.parse(localStorage.getItem(MSGS_KEY) || "[]"); } catch (e) { return []; }
  }

  // ── WebSocket ─────────────────────────────────────────────────────────────────
  function connectWS() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;

    const wsUrl = `${WS_URL}/ws/chat/${API_KEY}/${VISITOR_ID}`;
    console.log("[ChatWidget] Connecting to WS:", wsUrl);
    socket = new WebSocket(wsUrl);

    socket.onopen = () => console.log("[ChatWidget] WS connected");

    socket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      console.log("[ChatWidget] Received WS message:", data);

      if (data.type === "history") {
        if (data.messages && data.messages.length > 0) {
          messages = data.messages;
          saveMessages();
          renderMessages();
        }
        return;
      }

      if (data.type === "typing") {
        showTyping(true);
        return;
      }

      if (data.type === "message") {
        showTyping(false);
        if (data.ai_message) {
          const msg = { role: "assistant", content: data.ai_message.content, created_at: new Date().toISOString() };
          messages.push(msg);
          appendMessage(msg.role, msg.content, msg.created_at);
          saveMessages();
        }
        return;
      }

      if (data.type === "error") {
        showTyping(false);
        console.error("[ChatWidget] Server error:", data.message);
      }
    };

    socket.onerror = (err) => {
      console.warn("[ChatWidget] WS error:", err);
    };

    socket.onclose = () => {
      console.log("[ChatWidget] WS closed");
      socket = null;
    };
  }

  // ── HTTP Fallback ─────────────────────────────────────────────────────────────
  async function sendViaHTTP(content) {
    console.log("[ChatWidget] Sending via HTTP...");
    showTyping(true);
    try {
      const url = `${BASE_URL}/api/v1/public/conversations/message?api_key=${API_KEY}&visitor_id=${VISITOR_ID}`;
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, visitor_name: localStorage.getItem("cs_visitor_name") }),
      });
      
      if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
      
      const data = await res.json();
      console.log("[ChatWidget] HTTP response:", data);
      showTyping(false);
      
      if (data.ai_message) {
        const msg = { role: "assistant", content: data.ai_message.content, created_at: new Date().toISOString() };
        messages.push(msg);
        appendMessage(msg.role, msg.content, msg.created_at);
        saveMessages();
      }
    } catch (e) {
      console.error("[ChatWidget] HTTP send failed:", e);
      showTyping(false);
      appendMessage("assistant", "Sorry, I'm having trouble connecting. Please try again.");
    }
  }

  function renderMessages() {
    const existing = msgsEl.querySelectorAll(".cs-msg");
    existing.forEach(el => el.remove());
    if (messages.length === 0) {
      if (emptyEl) emptyEl.style.display = "block";
    } else {
      if (emptyEl) emptyEl.style.display = "none";
      messages.forEach(m => appendMessage(m.role, m.content, m.created_at));
    }
  }

  // ── Load history on first open ────────────────────────────────────────────────
  async function loadHistory() {
    console.log("[ChatWidget] Loading history...");
    try {
      const res = await fetch(
        `${BASE_URL}/api/v1/public/conversations/history?api_key=${API_KEY}&visitor_id=${VISITOR_ID}`
      );
      if (res.ok) {
        const data = await res.json();
        if (data && data.length > 0) {
          messages = data;
          saveMessages();
          renderMessages();
          return;
        }
      }
    } catch (e) {
      console.warn("[ChatWidget] Could not load history from server, using local storage");
    }
    
    // Fallback to local storage
    const local = loadLocalMessages();
    if (local.length > 0) {
      messages = local;
      renderMessages();
    }
  }

  // ── Send message ──────────────────────────────────────────────────────────────
  function sendMessage() {
    const content = inputEl.value.trim();
    if (!content) return;

    console.log("[ChatWidget] Sending message:", content);
    const userMsg = { role: "user", content, created_at: new Date().toISOString() };
    messages.push(userMsg);
    appendMessage("user", content, userMsg.created_at);
    saveMessages();
    
    inputEl.value = "";
    inputEl.style.height = "auto";

    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "message", content }));
    } else {
      sendViaHTTP(content);
    }
  }

  // ── Toggle window ─────────────────────────────────────────────────────────────
  let historyLoaded = false;
  btn.addEventListener("click", async () => {
    isOpen = !isOpen;
    win.classList.toggle("open", isOpen);
    btn.innerHTML = isOpen
      ? `<svg viewBox="0 0 24 24"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>`
      : `<svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>`;

    if (isOpen) {
      connectWS();
      if (!historyLoaded) {
        historyLoaded = true;
        await loadHistory();
      }
      inputEl.focus();
    }
  });

  // ── Input events ──────────────────────────────────────────────────────────────
  sendBtn.addEventListener("click", sendMessage);
  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
  inputEl.addEventListener("input", () => {
    inputEl.style.height = "auto";
    inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + "px";
  });
})();
