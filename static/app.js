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

  // DOM Elements - History Drawer
  const conversationListEl = document.getElementById("conversation-list");
  const btnNewChatEl = document.getElementById("btn-new-chat");
  const inputUserIdEl = document.getElementById("input-user-id");

  // State
  let currentConversationId = generateUUID();
  let currentUserId = inputUserIdEl.value.trim() || "analyst_test_user";
  let isGenerating = false;

  // Configure Marked Markdown Renderer for Beautiful Tables & Links (compatible with marked v12-v15+)
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

  // Normalize line endings to ensure consistent GFM rendering
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

  // Initialize
  updateCurrentChatTitle("Percakapan Baru");
  checkApiHealth();
  loadConversations();

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
    historyDrawerEl.classList.remove("open");
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

  function toggleHistoryDrawer() {
    historyDrawerEl.classList.toggle("open");
  }

  widgetFabEl.addEventListener("click", togglePopup);
  btnClosePopupEl.addEventListener("click", closePopup);
  btnToggleFullscreenEl.addEventListener("click", toggleFullscreen);
  btnToggleHistoryEl.addEventListener("click", toggleHistoryDrawer);
  btnCloseDrawerEl.addEventListener("click", () => historyDrawerEl.classList.remove("open"));

  // Keyboard shortcut: Escape to close drawer or popup
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (historyDrawerEl.classList.contains("open")) {
        historyDrawerEl.classList.remove("open");
      } else if (chatPopupEl.classList.contains("open")) {
        closePopup();
      }
    }
  });

  // ─── Input & Form Handling ─────────────────────────────────────

  btnNewChatEl.addEventListener("click", () => {
    startNewChat();
    historyDrawerEl.classList.remove("open");
  });

  inputUserIdEl.addEventListener("change", () => {
    currentUserId = inputUserIdEl.value.trim() || "analyst_test_user";
    loadConversations();
  });

  // Auto-resize input textarea
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

  // Quick Prompt Chips delegation
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

  function generateUUID() {
    return "conv-" + Math.random().toString(36).substring(2, 9) + "-" + Date.now().toString(36);
  }

  function updateCurrentChatTitle(title) {
    currentChatTitleEl.textContent = title;
  }

  function startNewChat() {
    currentConversationId = generateUUID();
    updateCurrentChatTitle("Percakapan Baru");
    messagesContainerEl.innerHTML = "";
    if (welcomeCardEl) {
      messagesContainerEl.appendChild(welcomeCardEl);
      welcomeCardEl.style.display = "block";
    }
    chatInputEl.value = "";
    chatInputEl.style.height = "auto";
    chatInputEl.focus();
    highlightActiveConversation(null);
  }

  async function checkApiHealth() {
    try {
      const res = await fetch("/api/v1/health");
      if (!res.ok) throw new Error("Healthcheck status not 200");
      const data = await res.json();
      apiStatusDotEl.className = "status-indicator-dot online";
      apiStatusDotEl.title = `Terkoneksi: ${data.postgres_db} | Model: ${data.model}`;
    } catch (err) {
      apiStatusDotEl.className = "status-indicator-dot offline";
      apiStatusDotEl.title = "Offline / Gagal terhubung ke API";
    }
  }

  async function loadConversations() {
    try {
      const res = await fetch(`/api/v1/conversations?user_id=${encodeURIComponent(currentUserId)}`);
      if (!res.ok) throw new Error("Failed to fetch conversations");
      const list = await res.json();

      conversationListEl.innerHTML = "";
      if (!list || list.length === 0) {
        conversationListEl.innerHTML = `<li class="drawer-empty">Belum ada riwayat percakapan.</li>`;
        return;
      }

      list.forEach((item) => {
        const li = document.createElement("li");
        li.className = "drawer-item";
        li.setAttribute("data-id", item.id);
        if (item.id === currentConversationId) {
          li.classList.add("active");
        }

        li.innerHTML = `
          <span class="title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</span>
          <button class="btn-delete" title="Hapus sesi" data-id="${item.id}">✕</button>
        `;

        li.addEventListener("click", (e) => {
          if (e.target.closest(".btn-delete")) return;
          loadConversationMessages(item.id, item.title);
          historyDrawerEl.classList.remove("open");
        });

        li.querySelector(".btn-delete").addEventListener("click", async (e) => {
          e.stopPropagation();
          if (confirm(`Hapus sesi "${item.title}"?`)) {
            await deleteConversation(item.id);
          }
        });

        conversationListEl.appendChild(li);
      });
    } catch (err) {
      conversationListEl.innerHTML = `<li class="drawer-empty">Gagal memuat: ${escapeHtml(err.message)}</li>`;
    }
  }

  async function deleteConversation(id) {
    try {
      await fetch(`/api/v1/conversations/${encodeURIComponent(id)}`, { method: "DELETE" });
      if (id === currentConversationId) {
        startNewChat();
      }
      loadConversations();
    } catch (err) {
      alert("Gagal menghapus percakapan: " + err.message);
    }
  }

  async function loadConversationMessages(conversationId, title) {
    currentConversationId = conversationId;
    updateCurrentChatTitle(title);
    highlightActiveConversation(conversationId);

    if (welcomeCardEl) {
      welcomeCardEl.style.display = "none";
    }
    messagesContainerEl.innerHTML = `<div class="drawer-empty">Memuat pesan...</div>`;

    try {
      const res = await fetch(`/api/v1/conversations/${encodeURIComponent(conversationId)}`);
      if (!res.ok) throw new Error("Gagal mengambil pesan");
      const messages = await res.json();

      messagesContainerEl.innerHTML = "";
      if (messages.length === 0) {
        messagesContainerEl.innerHTML = `<div class="drawer-empty">Percakapan kosong.</div>`;
        return;
      }

      messages.forEach((msg) => {
        const isAi = (msg.role === "ai" || msg.role === "assistant");
        appendMessageBubble(isAi ? "ai" : "human", msg.content, isAi);
      });
      scrollToBottom();
    } catch (err) {
      messagesContainerEl.innerHTML = `<div class="drawer-empty">Error: ${escapeHtml(err.message)}</div>`;
    }
  }

  function highlightActiveConversation(id) {
    document.querySelectorAll(".drawer-item").forEach((el) => {
      if (el.getAttribute("data-id") === id) {
        el.classList.add("active");
      } else {
        el.classList.remove("active");
      }
    });
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

  // ─── Real-time SSE Chat Streaming ──────────────────────────────

  async function sendMessage(query) {
    isGenerating = true;
    chatInputEl.value = "";
    chatInputEl.style.height = "auto";
    chatInputEl.disabled = true;
    btnSendEl.disabled = true;

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

    setBubbleThinking("Menghubungkan ke agen analitik...");

    liveIndicatorEl.classList.remove("hidden");
    liveIndicatorTextEl.textContent = "Menganalisis permintaan...";

    let fullAiResponse = "";

    try {
      const response = await fetch("/api/v1/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "text/event-stream",
        },
        body: JSON.stringify({
          query: query,
          conversation_id: currentConversationId,
          user_id: currentUserId,
          enable_pii: togglePiiEl.checked,
        }),
      });

      if (!response.ok) {
        const errText = await response.text();
        throw new Error(`HTTP ${response.status}: ${errText}`);
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
          const jsonStr = line.replace("data:", "").trim();
          if (!jsonStr) continue;

          try {
            const data = JSON.parse(jsonStr);
            const step = data.step;

            if (step === "START") {
              setBubbleThinking("Menganalisis permintaan...");
            } else if (step === "TITLE") {
              if (data.content) {
                updateCurrentChatTitle(data.content);
                loadConversations();
              }
            } else if (step === "TOOL_CALL") {
              setBubbleThinking("Mengeksekusi query basis data & aturan domain...");
              liveIndicatorTextEl.textContent = "Mengeksekusi query database & aturan domain...";
            } else if (step === "AIMessageChunk") {
              aiBubble.classList.remove("is-thinking");
              fullAiResponse += data.content || "";
              aiBubble.innerHTML = renderMarkdown(fullAiResponse);
              scrollToBottom();
            } else if (step === "END") {
              aiBubble.classList.remove("is-thinking");
              if (data.content) {
                fullAiResponse = data.content;
              }
              aiBubble.innerHTML = renderMarkdown(fullAiResponse);
            } else if (step === "ERROR") {
              aiBubble.classList.remove("is-thinking");
              aiBubble.innerHTML = `<div style="color: var(--status-error);">Peringatan: ${escapeHtml(data.content)}</div>`;
            }
          } catch (e) {
            console.warn("Parse error for chunk:", jsonStr, e);
          }
        }
      }
    } catch (err) {
      aiBubble.innerHTML = `<div style="color: var(--status-error);">Gagal mendapatkan respons: ${escapeHtml(err.message)}</div>`;
    } finally {
      isGenerating = false;
      chatInputEl.disabled = false;
      btnSendEl.disabled = false;
      liveIndicatorEl.classList.add("hidden");
      chatInputEl.focus();
      loadConversations();
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
