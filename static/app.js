// Synchrono AI Assistant - Interactive Pop-up Chat Widget Client Logic

document.addEventListener("DOMContentLoaded", () => {
  // DOM Elements - Widget Controls
  const widgetFabEl = document.getElementById("widget-fab");
  const chatPopupEl = document.getElementById("chat-popup");
  const btnClosePopupEl = document.getElementById("btn-close-popup");
  const btnToggleFullscreenEl = document.getElementById("btn-toggle-fullscreen");
  const btnToggleHistoryEl = document.getElementById("btn-toggle-history");
  const historyDrawerEl = document.getElementById("history-drawer");
  const btnCloseDrawerEl = document.getElementById("btn-close-drawer");
  const iconOpenEl = widgetFabEl.querySelector(".icon-open");
  const iconCloseEl = widgetFabEl.querySelector(".icon-close");
  const iconExpandEl = btnToggleFullscreenEl.querySelector(".icon-expand");
  const iconCollapseEl = btnToggleFullscreenEl.querySelector(".icon-collapse");

  // DOM Elements - Chat Area
  const messagesContainerEl = document.getElementById("messages-container");
  const welcomeCardEl = document.getElementById("welcome-card");
  const chatFormEl = document.getElementById("chat-form");
  const chatInputEl = document.getElementById("chat-input");
  const btnSendEl = document.getElementById("btn-send");
  const currentChatTitleEl = document.getElementById("current-chat-title");
  const apiStatusDotEl = document.getElementById("api-status-dot");
  const liveIndicatorEl = document.getElementById("live-indicator");
  const liveIndicatorTextEl = document.getElementById("live-indicator-text");
  const togglePiiEl = document.getElementById("toggle-pii");

  // DOM Elements - Connection & User Config
  const inputConnectionIdEl = document.getElementById("input-connection-id");
  const inputUserIdEl = document.getElementById("input-user-id");
  const conversationListEl = document.getElementById("conversation-list");
  const btnNewChatEl = document.getElementById("btn-new-chat");

  // State Management
  let currentThreadId = generateUUID();
  let currentUserId = initUserId();
  let currentConnectionId = initConnectionId();
  let isGenerating = false;

  // Configure Marked Markdown Renderer
  if (typeof marked !== "undefined") {
    marked.use({
      renderer: {
        table(token) {
          try {
            let headerHtml = "";
            if (token && Array.isArray(token.header)) {
              for (const cell of token.header) {
                headerHtml += this.tablecell(cell);
              }
            }
            let bodyHtml = "";
            if (token && Array.isArray(token.rows)) {
              for (const row of token.rows) {
                let rowHtml = "";
                for (const cell of row) {
                  rowHtml += this.tablecell(cell);
                }
                bodyHtml += this.tablerow({ text: rowHtml });
              }
            }
            return `<div class="table-wrapper"><table>\n<thead>\n${this.tablerow({ text: headerHtml })}</thead>\n${bodyHtml ? `<tbody>\n${bodyHtml}</tbody>\n` : ""}</table></div>\n`;
          } catch (e) {
            console.error("Table render error:", e);
            return token.raw || "";
          }
        },
        link(token) {
          try {
            let cleanHref = (token && token.href) ? token.href : "";
            cleanHref = cleanHref.replace(/^https?:\/\/synchrono\.internal/i, "");
            let text = "";
            if (token && token.tokens) {
              text = this.parser.parseInline(token.tokens);
            } else if (token && token.text) {
              text = escapeHtml(token.text);
            }
            const titleAttr = (token && token.title) ? ` title="${escapeHtml(token.title)}"` : "";
            return `<a href="${escapeHtml(cleanHref)}"${titleAttr} target="_blank" rel="noopener noreferrer">${text}</a>`;
          } catch (e) {
            console.error("Link render error:", e);
            return token.raw || "";
          }
        }
      },
      breaks: true,
      gfm: true
    });
  }

  function formatMarkdown(content) {
    if (!content) return "";
    return content.replace(/\r\n/g, "\n");
  }

  function renderMarkdown(content) {
    if (!content) return "";
    if (typeof marked !== "undefined") {
      try {
        return marked.parse(formatMarkdown(content));
      } catch (e) {
        console.warn("Marked parse error, fallback to text:", e);
      }
    }
    return escapeHtml(content);
  }

  // ─── UUID & Config Initialization ───────────────────────────────

  function generateUUID() {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      const v = c === "x" ? r : (r & 0x3 | 0x8);
      return v.toString(16);
    });
  }

  function sanitizeUserId(val) {
    const cleaned = (val || "").trim().slice(0, 36);
    return cleaned || generateUUID();
  }

  function initUserId() {
    let savedId = "";
    try {
      savedId = localStorage.getItem("synchrono_user_id");
    } catch (_) {}
    savedId = sanitizeUserId(savedId);
    try {
      localStorage.setItem("synchrono_user_id", savedId);
    } catch (_) {}
    if (inputUserIdEl) {
      inputUserIdEl.value = savedId;
    }
    return savedId;
  }

  function initConnectionId() {
    let savedConnId = "";
    try {
      savedConnId = (localStorage.getItem("synchrono_connection_id") || "").trim();
    } catch (_) {}
    if (inputConnectionIdEl) {
      inputConnectionIdEl.value = savedConnId;
    }
    return savedConnId;
  }

  if (inputConnectionIdEl) {
    inputConnectionIdEl.addEventListener("input", (e) => {
      currentConnectionId = (e.target.value || "").trim();
      try {
        localStorage.setItem("synchrono_connection_id", currentConnectionId);
      } catch (_) {}
      if (currentConnectionId) {
        inputConnectionIdEl.classList.remove("input-error");
        inputConnectionIdEl.removeAttribute("aria-invalid");
        inputConnectionIdEl.removeAttribute("aria-describedby");
        const existingAlert = document.getElementById("connection-id-error");
        if (existingAlert) {
          const row = existingAlert.closest(".message-row");
          if (row) row.remove();
          else existingAlert.remove();
        }
      }
    });
  }

  if (inputUserIdEl) {
    inputUserIdEl.addEventListener("change", (e) => {
      currentUserId = sanitizeUserId(e.target.value);
      inputUserIdEl.value = currentUserId;
      try {
        localStorage.setItem("synchrono_user_id", currentUserId);
      } catch (_) {}
    });
  }

  // ─── Startup & OpenAPI Route Verification ───────────────────────

  updateCurrentChatTitle("Percakapan Baru");
  updateHistoryDrawer();
  checkApiReadiness();

  async function checkApiReadiness() {
    if (!apiStatusDotEl) return;
    try {
      const res = await fetch("/openapi.json");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const spec = await res.json();
      const hasChatPost = !!(spec && spec.paths && spec.paths["/chat"] && spec.paths["/chat"].post);
      if (hasChatPost) {
        apiStatusDotEl.className = "status-indicator-dot online";
        apiStatusDotEl.title = "Endpoint POST /chat terdaftar di OpenAPI";
      } else {
        apiStatusDotEl.className = "status-indicator-dot warning";
        apiStatusDotEl.title = "Endpoint POST /chat tidak terdaftar";
      }
    } catch (err) {
      apiStatusDotEl.className = "status-indicator-dot offline";
      apiStatusDotEl.title = "Tidak dapat memeriksa OpenAPI: " + err.message;
    }
  }

  function updateHistoryDrawer() {
    if (!conversationListEl) return;
    conversationListEl.innerHTML = `
      <li class="drawer-empty">
        <div style="font-weight: 600; margin-bottom: 6px; color: var(--text-secondary);">Riwayat Server Tidak Tersedia</div>
        <div>API riwayat belum tersedia. Pesan pada tampilan akan hilang saat halaman dimuat ulang.</div>
        <div style="margin-top: 12px; font-size: 11px; color: var(--text-muted); font-family: var(--font-mono); word-break: break-all;">
          Thread ID: ${escapeHtml(currentThreadId)}
        </div>
      </li>
    `;
  }

  // ─── Pop-up & Widget Interactions ───────────────────────────────

  function openPopup() {
    chatPopupEl.classList.add("open");
    iconOpenEl.classList.add("hidden");
    iconCloseEl.classList.remove("hidden");
    chatInputEl.focus();
  }

  function closePopup() {
    chatPopupEl.classList.remove("open");
    iconOpenEl.classList.remove("hidden");
    iconCloseEl.classList.add("hidden");
    closeHistoryDrawer(false);
    if (widgetFabEl) {
      widgetFabEl.focus();
    }
  }

  function togglePopup() {
    if (chatPopupEl.classList.contains("open")) {
      closePopup();
    } else {
      openPopup();
    }
  }

  function toggleFullscreen() {
    chatPopupEl.classList.toggle("fullscreen");
    const isFullscreen = chatPopupEl.classList.contains("fullscreen");
    iconExpandEl.classList.toggle("hidden", isFullscreen);
    iconCollapseEl.classList.toggle("hidden", !isFullscreen);
  }

  function openHistoryDrawer() {
    historyDrawerEl.classList.add("open");
    historyDrawerEl.inert = false;
    historyDrawerEl.removeAttribute("inert");
    if (btnNewChatEl) btnNewChatEl.focus();
  }

  function closeHistoryDrawer(returnFocus = true) {
    if (!historyDrawerEl.classList.contains("open")) return;
    historyDrawerEl.classList.remove("open");
    historyDrawerEl.inert = true;
    historyDrawerEl.setAttribute("inert", "");
    if (returnFocus && btnToggleHistoryEl) {
      btnToggleHistoryEl.focus();
    }
  }

  function toggleHistoryDrawer() {
    if (historyDrawerEl.classList.contains("open")) {
      closeHistoryDrawer(true);
    } else {
      openHistoryDrawer();
    }
  }

  widgetFabEl.addEventListener("click", togglePopup);
  btnClosePopupEl.addEventListener("click", closePopup);
  btnToggleFullscreenEl.addEventListener("click", toggleFullscreen);
  btnToggleHistoryEl.addEventListener("click", toggleHistoryDrawer);
  btnCloseDrawerEl.addEventListener("click", () => closeHistoryDrawer(true));

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (historyDrawerEl.classList.contains("open")) {
        closeHistoryDrawer(true);
      } else if (chatPopupEl.classList.contains("open")) {
        closePopup();
      }
    }
  });

  // ─── Input & Form Handling ─────────────────────────────────────

  btnNewChatEl.addEventListener("click", () => {
    if (isGenerating) return;
    startNewChat();
    closeHistoryDrawer(false);
  });

  chatInputEl.addEventListener("input", () => {
    chatInputEl.style.height = "auto";
    chatInputEl.style.height = Math.min(chatInputEl.scrollHeight, 120) + "px";
  });

  chatInputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      chatFormEl.dispatchEvent(new Event("submit"));
    }
  });

  chatFormEl.addEventListener("submit", (e) => {
    e.preventDefault();
    const query = chatInputEl.value.trim();
    if (!query || isGenerating) return;
    sendMessage(query);
  });

  document.addEventListener("click", (e) => {
    const chip = e.target.closest(".prompt-chip");
    if (chip) {
      const query = chip.getAttribute("data-query");
      if (query && !isGenerating) {
        sendMessage(query);
      }
    }
  });

  // ─── Helpers ───────────────────────────────────────────────────

  function updateCurrentChatTitle(title) {
    if (currentChatTitleEl) currentChatTitleEl.textContent = title;
  }

  function startNewChat() {
    currentThreadId = generateUUID();
    updateCurrentChatTitle("Percakapan Baru");
    messagesContainerEl.innerHTML = "";
    if (welcomeCardEl) {
      messagesContainerEl.appendChild(welcomeCardEl);
      welcomeCardEl.style.display = "block";
    }
    chatInputEl.value = "";
    chatInputEl.style.height = "auto";
    if (inputConnectionIdEl) {
      inputConnectionIdEl.classList.remove("input-error");
      inputConnectionIdEl.removeAttribute("aria-invalid");
      inputConnectionIdEl.removeAttribute("aria-describedby");
    }
    chatInputEl.focus();
    updateHistoryDrawer();
  }

  function appendMessageBubble(role, content = "", isMarkdown = true) {
    if (welcomeCardEl && welcomeCardEl.style.display !== "none") {
      welcomeCardEl.style.display = "none";
    }

    const row = document.createElement("div");
    row.className = `message-row ${role}`;

    const meta = document.createElement("div");
    meta.className = "message-meta";
    meta.textContent = role === "human" ? "Anda" : "Synchrono AI";

    const bubble = document.createElement("div");
    bubble.className = "message-bubble";

    if (role === "ai" && isMarkdown) {
      bubble.innerHTML = renderMarkdown(content);
    } else if (role === "ai" && !isMarkdown) {
      bubble.innerHTML = content;
    } else {
      bubble.textContent = content;
    }

    row.appendChild(meta);
    row.appendChild(bubble);
    messagesContainerEl.appendChild(row);
    scrollToBottom();

    return bubble;
  }

  function scrollToBottom() {
    messagesContainerEl.scrollTop = messagesContainerEl.scrollHeight;
  }

  function setFormControlsDisabled(disabled) {
    chatInputEl.disabled = disabled;
    btnSendEl.disabled = disabled;
    if (btnNewChatEl) btnNewChatEl.disabled = disabled;
    if (inputUserIdEl) inputUserIdEl.disabled = disabled;
    if (inputConnectionIdEl) inputConnectionIdEl.disabled = disabled;
    if (togglePiiEl) togglePiiEl.disabled = disabled;
  }

  // ─── Real-time SSE Chat Streaming (POST /chat) ─────────────────

  async function sendMessage(query) {
    const connId = (inputConnectionIdEl ? inputConnectionIdEl.value : currentConnectionId).trim();

    // Required State: Connection Configuration Missing
    if (!connId) {
      if (inputConnectionIdEl) {
        inputConnectionIdEl.classList.add("input-error");
        inputConnectionIdEl.setAttribute("aria-invalid", "true");
        inputConnectionIdEl.setAttribute("aria-describedby", "connection-id-error");
        inputConnectionIdEl.focus();
      }
      const existingAlert = document.getElementById("connection-id-error");
      if (existingAlert) {
        const row = existingAlert.closest(".message-row");
        if (row) row.remove();
        else existingAlert.remove();
      }
      appendMessageBubble(
        "ai",
        `<div id="connection-id-error" class="message-alert warning" role="alert">
          <strong>Konfigurasi koneksi belum diisi.</strong><br>
          Kolom <code>connection_id</code> wajib diisi untuk menganalisis data. Masukkan ID koneksi database pada kolom di bawah.
        </div>`,
        false
      );
      return;
    }

    isGenerating = true;
    chatInputEl.value = "";
    chatInputEl.style.height = "auto";
    setFormControlsDisabled(true);

    // Append user message
    appendMessageBubble("human", query, false);

    // Append AI placeholder with thinking indicator
    const aiBubble = appendMessageBubble("ai", "", true);

    function setBubbleThinking(text) {
      aiBubble.classList.add("is-thinking");
      aiBubble.innerHTML = `
        <div class="bubble-thinking">
          <div class="typing-dots">
            <span></span><span></span><span></span>
          </div>
          <span class="thinking-text">${escapeHtml(text)}</span>
        </div>
      `;
      scrollToBottom();
    }

    // Required State: Connecting / Streaming
    setBubbleThinking("Menghubungkan ke endpoint /chat...");
    liveIndicatorEl.classList.remove("hidden");
    liveIndicatorTextEl.textContent = "Menganalisis permintaan...";

    let fullAiResponse = "";
    let receivedEnd = false;

    try {
      const response = await fetch("/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "text/event-stream",
        },
        body: JSON.stringify({
          user_id: currentUserId,
          thread_id: currentThreadId,
          question: query,
          connection_id: connId,
          enable_pii: togglePiiEl ? togglePiiEl.checked : true,
        }),
      });

      // Required State: Validation & HTTP Error Handling
      if (!response.ok) {
        let detail = "";
        try {
          const errData = await response.json();
          if (errData && errData.detail) {
            detail = Array.isArray(errData.detail)
              ? errData.detail.map((d) => `${d.loc ? d.loc.slice(1).join(".") : ""}: ${d.msg}`).join("; ")
              : String(errData.detail);
          }
        } catch (_) {
          try {
            detail = await response.text();
          } catch (_) {
            detail = response.statusText;
          }
        }
        throw new Error(`HTTP ${response.status}${detail ? `: ${detail}` : ""}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop();

        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          const jsonStr = line.replace(/^data:\s*/, "").trim();
          if (!jsonStr) continue;

          try {
            const data = JSON.parse(jsonStr);
            const step = data.step;

            if (step === "START") {
              setBubbleThinking("Menganalisis kueri analitik...");
            } else if (step === "TITLE") {
              if (data.content) {
                updateCurrentChatTitle(data.content);
              }
            } else if (step === "TOOL_CALL" || (data.tool_calls && data.tool_calls.length > 0)) {
              setBubbleThinking("Mengeksekusi kueri basis data...");
              liveIndicatorEl.classList.remove("hidden");
              liveIndicatorTextEl.textContent = "Mengeksekusi kueri basis data...";
            } else if (step === "AIMessageChunk") {
              if (data.content) {
                aiBubble.classList.remove("is-thinking");
                fullAiResponse += data.content;
                aiBubble.innerHTML = renderMarkdown(fullAiResponse);
                scrollToBottom();
              }
            } else if (step === "END") {
              receivedEnd = true;
              aiBubble.classList.remove("is-thinking");
              if (data.content) {
                fullAiResponse = data.content;
              }
              // Required State: Successful Reply or Empty Reply
              if (!fullAiResponse.trim()) {
                aiBubble.innerHTML = `<div class="message-alert error" role="alert">Server mengirimkan respons kosong.</div>`;
              } else {
                aiBubble.innerHTML = renderMarkdown(fullAiResponse);
              }
            } else if (step === "ERROR") {
              receivedEnd = true;
              aiBubble.classList.remove("is-thinking");
              aiBubble.innerHTML = `<div class="message-alert error" role="alert">Kesalahan server: ${escapeHtml(data.content || "Terjadi kesalahan internal")}</div>`;
            }
          } catch (e) {
            console.warn("Parse error for chunk:", jsonStr, e);
          }
        }
      }

      // Required State: Abrupt / Premature / Empty Stream Termination
      aiBubble.classList.remove("is-thinking");
      if (!receivedEnd) {
        if (fullAiResponse.trim()) {
          aiBubble.innerHTML =
            renderMarkdown(fullAiResponse) +
            `<div class="message-alert warning" role="alert">Aliran data terputus sebelum respons selesai.</div>`;
        } else {
          aiBubble.innerHTML = `<div class="message-alert error" role="alert">Koneksi streaming terputus tanpa balasan dari server.</div>`;
        }
      }
    } catch (err) {
      // Required State: Network & Fetch Failure (Preserve partial answer if tokens received)
      aiBubble.classList.remove("is-thinking");
      if (fullAiResponse.trim()) {
        aiBubble.innerHTML =
          renderMarkdown(fullAiResponse) +
          `<div class="message-alert error" role="alert">Aliran data terputus karena kesalahan: ${escapeHtml(err.message)}</div>`;
      } else {
        aiBubble.innerHTML = `<div class="message-alert error" role="alert">
          <strong>Gagal memproses pesan:</strong><br>
          ${escapeHtml(err.message)}
        </div>`;
      }
    } finally {
      isGenerating = false;
      setFormControlsDisabled(false);
      liveIndicatorEl.classList.add("hidden");
      chatInputEl.focus();
    }
  }

  function escapeHtml(str) {
    if (!str) return "";
    return str.replace(/[&<>"']/g, (m) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;"
    })[m]);
  }
});
