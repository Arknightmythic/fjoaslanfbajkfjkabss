# Integrasi React: Streaming Chat dan Markdown Rendering

Dokumen ini adalah acuan integrasi **UI portal ke API chatbot Synchrono**. Kontrak di bawah mengikuti implementasi aktual, bukan dokumentasi lama yang masih memakai `POST /api/v1/chat`, `query`, dan `conversation_id`.

**Base URL lokal:** `http://127.0.0.1:8001`  
**Endpoint chat:** `POST /chat`  
**Protokol:** Server-Sent Events (SSE) di atas `fetch` POST

---

## 1. Alur Integrasi

```text
React ChatWidget
  -> useChatStream()
  -> fetch POST /chat
  -> baca ReadableStream
  -> parse event SSE
  -> append AIMessageChunk ke state
  -> render dengan react-markdown
```

Jangan memakai `EventSource` bawaan browser. `EventSource` hanya mendukung `GET`, sedangkan endpoint chatbot memakai `POST` dengan body JSON.

---

## 2. Library yang Perlu Dipasang

```bash
npm install react-markdown remark-gfm rehype-sanitize eventsource-parser
```

Opsional untuk code block dan tampilan:

```bash
npm install rehype-highlight highlight.js
npm install -D @tailwindcss/typography
```

| Library | Fungsi | Wajib? |
|---|---|---|
| `react-markdown` | Render Markdown menjadi elemen React tanpa `dangerouslySetInnerHTML` | Ya |
| `remark-gfm` | Dukungan tabel, task list, strikethrough | Ya |
| `rehype-sanitize` | Sanitasi HTML dari output model | Disarankan |
| `eventsource-parser` | Parse chunk SSE yang bisa terpotong di tengah event | Disarankan |
| `rehype-highlight` + `highlight.js` | Syntax highlighting code block | Opsional |
| `@tailwindcss/typography` | Class `prose` untuk styling Markdown | Opsional |

Alternatif `eventsource-parser`: `@microsoft/fetch-event-source`. Untuk kebutuhan saat ini, `fetch` + `eventsource-parser` lebih mudah dikontrol dan tidak melakukan retry otomatis yang berpotensi menggandakan jawaban.

---

## 3. Kontrak API Aktual

### Request

```http
POST /chat
Content-Type: application/json
Accept: text/event-stream
```

```json
{
  "user_id": "portal-user-123",
  "thread_id": "4d3b7e2a-9b1f-4e9b-8f31-0e7e7f6b2a11",
  "question": "Apa kriteria umum Grade A?",
  "enable_pii": true
}
```

| Field | Tipe | Wajib | Keterangan |
|---|---|---|---|
| `user_id` | string | Ya | ID user portal, maksimal 36 karakter |
| `thread_id` | string | Ya | ID percakapan, maksimal 36 karakter; pakai UUID |
| `question` | string | Ya | Pertanyaan user |
| `enable_pii` | boolean | Tidak | Default `true`; masking NIK 16 digit |

Gunakan `thread_id` yang sama untuk lanjutan percakapan dalam satu sesi. Buat `thread_id` baru saat user memulai percakapan baru.

**Follow-up question:** didukung. Riwayat disimpan per `thread_id` di PostgreSQL. Backend memakai `SummarizationMiddleware` dengan trigger 15 pesan dan menyimpan 6 pesan terakhir; riwayat lama diringkas otomatis. Tidak ada batas jumlah turn yang hard-coded, tetapi panjang efektif tetap dibatasi context window model `gemma4:31b-cloud`. Untuk pertanyaan lanjutan, kirim `thread_id` yang sama dan pertanyaan baru; frontend tidak perlu mengirim ulang riwayat.

### Response SSE

Response berupa baris `data: <JSON>` dengan pemisah dua newline:

```text
data: {"step":"START","content":""}

data: {"step":"AIMessageChunk","content":"Kriteria umum Grade A adalah "}

data: {"step":"AIMessageChunk","content":"..."}

data: {"step":"END","content":""}
```

| Step | Handling di UI |
|---|---|
| `START` | Tampilkan indikator mengetik |
| `TITLE` | Update judul percakapan; bisa datang sebelum atau sesudah `END` |
| `AIMessageChunk` tanpa `tool_calls` | **Append** `content` ke jawaban assistant |
| `AIMessageChunk` dengan `tool_calls` | Tampilkan status proses; jangan append |
| `ToolMessage` | Tampilkan status proses; jangan append |
| `END` | Akhiri status streaming; `content` kosong |
| `ERROR` | Tampilkan error jika ada |

Catatan penting:

- Backend saat ini **tidak mengirim** `step: "TOOL_CALL"`. Tool call muncul sebagai `AIMessageChunk` dengan field `tool_calls`, lalu hasilnya sebagai `ToolMessage`.
- `AIMessageChunk` bisa berisi potongan token, tetapi pada cache hit bisa berisi **satu jawaban penuh**. Selalu append, jangan replace.
- `END` tidak berisi jawaban. Jangan mengambil `content` dari event ini.
- Backend mengirim `ERROR` berisi fallback generik saat eksekusi stream gagal. Kegagalan koneksi tetap bisa memutus stream tanpa `END`, jadi frontend harus menganggap stream yang berhenti tanpa `END` sebagai error.
- Endpoint health check: `GET /api/v1/health`.

---

## 4. Hook `useChatStream`

Tambahkan base URL API ke environment portal:

```env
VITE_CHATBOT_API_URL=http://127.0.0.1:8001
```

Buat file `src/features/chat/useChatStream.ts`:

```ts
import { useCallback, useEffect, useRef, useState } from "react";
import { createParser } from "eventsource-parser";

type ChatRole = "user" | "assistant";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
}

interface ServerEvent {
  step: string;
  content?: string;
  tool_calls?: unknown[];
}

const API_URL = (
  import.meta.env.VITE_CHATBOT_API_URL ?? "http://127.0.0.1:8001"
).replace(/\/$/, "");

export function useChatStream(userId: string) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [threadId, setThreadId] = useState(() => crypto.randomUUID());
  const [title, setTitle] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const streamingRef = useRef(false);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const send = useCallback(
    async (question: string) => {
      const text = question.trim();
      if (!text || streamingRef.current) return;

      streamingRef.current = true;
      setIsStreaming(true);
      setError(null);
      setStatus(null);

      const assistantId = crypto.randomUUID();
      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: "user", content: text },
        { id: assistantId, role: "assistant", content: "" },
      ]);

      const controller = new AbortController();
      abortRef.current = controller;
      let sawEnd = false;

      try {
        const response = await fetch(`${API_URL}/chat`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "text/event-stream",
          },
          body: JSON.stringify({
            user_id: userId,
            thread_id: threadId,
            question: text,
            enable_pii: true,
          }),
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(
            (await response.text()) || `HTTP ${response.status}`
          );
        }

        if (!response.body) {
          throw new Error("Browser tidak mendukung streaming response.");
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        const parser = createParser({
          onEvent(event) {
            if (!event.data) return;

            let payload: ServerEvent;
            try {
              payload = JSON.parse(event.data) as ServerEvent;
            } catch {
              return;
            }

            if (payload.step === "AIMessageChunk") {
              if (payload.tool_calls?.length) {
                setStatus("Menganalisis data...");
                return;
              }

              const chunk = payload.content ?? "";
              if (!chunk) return;

              setMessages((prev) =>
                prev.map((message) =>
                  message.id === assistantId
                    ? { ...message, content: message.content + chunk }
                    : message
                )
              );
            } else if (payload.step === "TITLE") {
              setTitle(payload.content ?? "");
            } else if (payload.step === "ToolMessage") {
              setStatus("Menganalisis data...");
            } else if (payload.step === "END") {
              sawEnd = true;
              setStatus(null);
            } else if (payload.step === "ERROR") {
              setError(payload.content || "Terjadi kesalahan pada chatbot.");
              controller.abort();
            }
          },
        });

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          parser.feed(decoder.decode(value, { stream: true }));
        }
        parser.feed(decoder.decode());

        if (!sawEnd && !controller.signal.aborted) {
          setError("Koneksi berakhir sebelum jawaban selesai.");
        }
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          setError((err as Error).message || "Gagal terhubung ke chatbot.");
        }
      } finally {
        streamingRef.current = false;
        setIsStreaming(false);
        setStatus(null);
        abortRef.current = null;
      }
    },
    [threadId, userId]
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
    setTitle("");
    setStatus(null);
    setError(null);
    setThreadId(crypto.randomUUID());
  }, []);

  return {
    messages,
    send,
    stop,
    reset,
    isStreaming,
    status,
    title,
    error,
    threadId,
  };
}
```

Catatan:

- `user_id` dan `thread_id` dibatasi 36 karakter oleh backend.
- `crypto.randomUUID()` membutuhkan HTTPS atau `localhost`.
- Untuk chat panjang, update state per token bisa berat. Buffer chunk di `ref`, lalu flush dengan `requestAnimationFrame` atau interval 30-50 ms.
- Jangan membuat `threadId` baru di setiap request; itu akan memutus konteks percakapan.

---

## 5. Komponen Markdown

Buat `src/features/chat/MarkdownMessage.tsx`:

```tsx
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";
import rehypeHighlight from "rehype-highlight";
import "highlight.js/styles/github-dark.css";

export function MarkdownMessage({ content }: { content: string }) {
  return (
    <div className="chat-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize, rehypeHighlight]}
        components={{
          a: ({ node: _node, ...props }) => (
            <a {...props} target="_blank" rel="noopener noreferrer" />
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
```

`react-markdown` tidak merender HTML mentah secara default. Jangan menambahkan `rehype-raw` kecuali benar-benar perlu dan sumbernya tepercaya. Untuk output model yang tidak tepercaya, biarkan sanitasi aktif.

Saat streaming, Markdown bisa terbaca setengah jadi (misalnya `**` belum ditutup). Itu normal. Jika ingin format hanya muncul setelah jawaban selesai, tampilkan teks polos selama streaming lalu render Markdown saat event `END`.

Jika tidak memakai syntax highlighting, hapus `rehype-highlight` dan import CSS `highlight.js`.

---

## 6. Komponen Chat

Buat `src/features/chat/ChatWidget.tsx`:

```tsx
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { MarkdownMessage } from "./MarkdownMessage";
import { useChatStream } from "./useChatStream";
import "./ChatWidget.css";

export function ChatWidget({ userId }: { userId: string }) {
  const {
    messages,
    send,
    stop,
    reset,
    isStreaming,
    status,
    error,
  } = useChatStream(userId);

  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!input.trim() || isStreaming) return;

    void send(input);
    setInput("");
  }

  return (
    <section className="chat-widget">
      <header className="chat-widget__header">
        <div>
          <strong>Synchrono AI Assistant</strong>
          <span>Analisis dan penjelasan data</span>
        </div>
        <button type="button" onClick={reset} disabled={isStreaming}>
          Chat baru
        </button>
      </header>

      <div className="chat-widget__messages">
        {messages.map((message) => (
          <div
            key={message.id}
            className={`chat-bubble chat-bubble--${message.role}`}
          >
            {message.role === "assistant" ? (
              message.content ? (
                <MarkdownMessage content={message.content} />
              ) : (
                <span className="chat-typing">Sedang menyusun jawaban...</span>
              )
            ) : (
              <p>{message.content}</p>
            )}
          </div>
        ))}

        {status && <div className="chat-status">{status}</div>}
        {error && <div className="chat-error">{error}</div>}
        <div ref={bottomRef} />
      </div>

      <form className="chat-widget__composer" onSubmit={handleSubmit}>
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Tanyakan sesuatu tentang data Synchrono..."
          rows={2}
          disabled={isStreaming}
        />
        {isStreaming ? (
          <button type="button" onClick={stop}>
            Stop
          </button>
        ) : (
          <button type="submit" disabled={!input.trim()}>
            Kirim
          </button>
        )}
      </form>
    </section>
  );
}
```

Pasang di portal:

```tsx
<ChatWidget userId={session.user.id} />
```

Pastikan `userId` berasal dari sesi login dan panjangnya maksimal 36 karakter.

---

## 7. Styling Markdown

Contoh `ChatWidget.css`:

```css
.chat-widget {
  display: flex;
  flex-direction: column;
  height: 620px;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  overflow: hidden;
  background: #fff;
}

.chat-widget__messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  background: #f8fafc;
}

.chat-bubble {
  max-width: 85%;
  margin-bottom: 12px;
  padding: 10px 14px;
  border-radius: 14px;
  font-size: 14px;
}

.chat-bubble--user {
  margin-left: auto;
  background: #1d4ed8;
  color: #fff;
}

.chat-bubble--assistant {
  margin-right: auto;
  background: #fff;
  border: 1px solid #e2e8f0;
}

.chat-markdown {
  line-height: 1.65;
  overflow-wrap: anywhere;
}

.chat-markdown > :first-child {
  margin-top: 0;
}

.chat-markdown > :last-child {
  margin-bottom: 0;
}

.chat-markdown p {
  margin: 0 0 0.75rem;
}

.chat-markdown h1,
.chat-markdown h2,
.chat-markdown h3 {
  margin: 1rem 0 0.5rem;
  font-weight: 700;
  line-height: 1.3;
}

.chat-markdown h1 { font-size: 1.25rem; }
.chat-markdown h2 { font-size: 1.1rem; }
.chat-markdown h3 { font-size: 1rem; }

.chat-markdown ul,
.chat-markdown ol {
  margin: 0 0 0.75rem;
  padding-left: 1.25rem;
}

.chat-markdown ul { list-style: disc; }
.chat-markdown ol { list-style: decimal; }
.chat-markdown li { margin: 0.25rem 0; }

.chat-markdown strong {
  font-weight: 700;
}

.chat-markdown a {
  color: #1d4ed8;
  text-decoration: underline;
}

.chat-markdown blockquote {
  margin: 0.75rem 0;
  padding-left: 0.75rem;
  border-left: 3px solid #cbd5e1;
  color: #475569;
}

.chat-markdown code:not(pre code) {
  padding: 0.15rem 0.35rem;
  border-radius: 0.35rem;
  background: #f1f5f9;
  font-size: 0.875em;
}

.chat-markdown pre {
  margin: 0.75rem 0;
  padding: 0.875rem 1rem;
  overflow-x: auto;
  border-radius: 0.75rem;
  background: #0f172a;
  color: #e2e8f0;
}

.chat-markdown pre code {
  background: transparent;
  color: inherit;
}

.chat-markdown table {
  display: block;
  width: 100%;
  overflow-x: auto;
  border-collapse: collapse;
  margin: 0.75rem 0;
}

.chat-markdown th,
.chat-markdown td {
  padding: 0.5rem 0.65rem;
  border: 1px solid #e2e8f0;
  text-align: left;
}

.chat-markdown th {
  background: #f1f5f9;
  font-weight: 600;
}

.chat-widget__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #e2e8f0;
}

.chat-widget__header span {
  display: block;
  margin-top: 2px;
  color: #64748b;
  font-size: 12px;
}

.chat-widget__composer {
  display: flex;
  gap: 8px;
  padding: 12px;
  border-top: 1px solid #e2e8f0;
}

.chat-widget__composer textarea {
  flex: 1;
  resize: none;
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  padding: 10px;
  font: inherit;
}

.chat-widget__composer button {
  align-self: flex-end;
  border: 0;
  border-radius: 10px;
  padding: 10px 16px;
  background: #1d4ed8;
  color: #fff;
  cursor: pointer;
}

.chat-widget__composer button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.chat-typing,
.chat-status {
  color: #64748b;
  font-size: 13px;
}

.chat-error {
  margin-top: 8px;
  color: #b91c1c;
  font-size: 13px;
}
```

Jika memakai Tailwind, styling Markdown bisa lebih singkat dengan `@tailwindcss/typography`:

```tsx
<div className="prose prose-sm max-w-none prose-p:my-2 prose-pre:bg-slate-900">
  <MarkdownMessage content={content} />
</div>
```

---

## 8. Catatan Production

Sebelum dipakai portal publik:

- **Autentikasi:** endpoint `/chat` saat ini belum memakai auth. Jangan taruh API key di frontend. Idealnya portal memanggil backend/BFF yang sudah terautentikasi, atau backend chatbot ditambah validasi JWT/API key.
- **CORS:** server saat ini memakai `allow_origins=["*"]`. Batasi ke origin portal sebelum production.
- **HTTPS:** gunakan reverse proxy HTTPS.
- **Proxy buffering:** pastikan Nginx/ingress tidak membuffer SSE. Contoh Nginx:
  ```nginx
  proxy_buffering off;
  proxy_cache off;
  proxy_read_timeout 3600s;
  ```
- **Timeout:** jangan set timeout frontend terlalu pendek; jawaban LLM bisa puluhan detik. Gunakan tombol Stop/AbortController.
- **Sanitasi:** jangan render output model dengan `dangerouslySetInnerHTML`.
- **Thread:** simpan `threadId` selama percakapan; reset saat user memilih "Chat baru".
- **PII:** biarkan `enable_pii: true` kecuali ada kebutuhan khusus.
- **Cache:** jawaban cache dikirim sebagai satu `AIMessageChunk`; UI tidak perlu membedakan cache hit dan hasil model.

---

## 9. Tes Cepat

```powershell
curl.exe -N -X POST "http://127.0.0.1:8001/chat" `
  -H "Content-Type: application/json" `
  -H "Accept: text/event-stream" `
  --data-raw '{"user_id":"portal-user","thread_id":"portal-thread-1","question":"Apa kriteria umum Grade A?","enable_pii":true}'
```

Yang harus terlihat: `START`, satu atau beberapa `AIMessageChunk`, lalu `END`. Kalau koneksi berhenti tanpa `END`, UI harus menampilkan error dan menyediakan tombol kirim ulang.
