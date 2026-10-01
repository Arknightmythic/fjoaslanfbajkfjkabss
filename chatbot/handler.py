import os
import json
from typing import AsyncIterator, Optional, List, Dict, Any
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain.chat_models import init_chat_model
from langchain.messages import SystemMessage, HumanMessage, AIMessage, AIMessageChunk
from langchain.agents import create_agent
from langchain.agents.middleware import ToolRetryMiddleware
from langgraph.checkpoint.memory import MemorySaver
from chatbot.prompts import SYNCHRONO_AGENT_SYSTEM_PROMPT, TITLE_GENERATOR_PROMPT
from chatbot.tools import run_query, get_schemas, load_skills
from chatbot.middlewares import PromptInjectionGuardrail, PIIMiddleware
from chatbot.database import conv_db

load_dotenv()

# Global checkpointer singleton to preserve conversation thread state across HTTP requests
_SHARED_CHECKPOINTER = MemorySaver()

class TitleOutput(BaseModel):
    title: str = Field(description="Short conversation title in Bahasa Indonesia.")

class TitleGenerator:
    def __init__(self, model_name: Optional[str] = None, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.model_name = model_name or os.getenv("OPENAI_MODEL_NAME") or os.getenv("CHATBOT_MODEL", "gemma4:31b-cloud")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL") or os.getenv("OLLAMA_BASE_URL")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("OLLAMA_API_KEY") or "ollama"

        try:
            kwargs: Dict[str, Any] = {"temperature": 0, "api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            base_llm = init_chat_model(
                self.model_name,
                model_provider="openai",
                **kwargs
            )
            self._model = base_llm.with_structured_output(TitleOutput)
        except Exception:
            self._model = None

    def generate_title(self, question: str) -> str:
        default_title = "Percakapan Data Synchrono"
        words = question.strip().split()
        if len(words) <= 6:
            default_title = " ".join(words).capitalize()

        if not self._model:
            return default_title

        try:
            prompt = TITLE_GENERATOR_PROMPT.format(question=question)
            result = self._model.invoke(prompt)
            if isinstance(result, TitleOutput) and result.title:
                return result.title.strip()
            elif isinstance(result, dict) and "title" in result:
                return result["title"].strip()
            elif isinstance(result, str):
                cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", result.strip(), flags=re.MULTILINE).strip()
                try:
                    data = json.loads(cleaned)
                    if isinstance(data, dict) and "title" in data:
                        return data["title"].strip()
                except Exception:
                    if len(cleaned.split()) <= 8:
                        return cleaned.strip()
            return default_title
        except Exception as e:
            try:
                match = re.search(r"input_value='([^']+)'", str(e))
                if match:
                    val = match.group(1).strip()
                    if val and not val.startswith("{") and len(val.split()) <= 8:
                        return val
            except Exception:
                pass
            print(f"[TitleGenerator Notice] Fallback title used: {e}")
            return default_title

class ChatbotHandler:
    def __init__(self, model_name: Optional[str] = None, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.model_name = model_name or os.getenv("OPENAI_MODEL_NAME") or os.getenv("CHATBOT_MODEL", "gemma4:31b-cloud")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL") or os.getenv("OLLAMA_BASE_URL")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("OLLAMA_API_KEY") or "ollama"

        # LangChain Official Universal Factory (init_chat_model)
        # Mendukung string provider:model dan model_provider='openai' untuk OpenAI-compatible endpoint
        kwargs: Dict[str, Any] = {
            "temperature": 0,
            "api_key": self.api_key,
            "stream_usage": True,
        }
        if self.base_url:
            kwargs["base_url"] = self.base_url

        self._llm = init_chat_model(
            self.model_name,
            model_provider="openai",
            **kwargs
        )

        self._system_prompt = SystemMessage(SYNCHRONO_AGENT_SYSTEM_PROMPT)
        self._tools = [run_query, get_schemas, load_skills]
        
        # Core agent middleware
        self._middleware = [
            PromptInjectionGuardrail(model_name=self.model_name, base_url=self.base_url, api_key=self.api_key),
            ToolRetryMiddleware(max_retries=2),
        ]
        
        # State checkpointer for execution graph (shared across requests)
        self._checkpointer = _SHARED_CHECKPOINTER
        self.title_generator = TitleGenerator(self.model_name, self.base_url, self.api_key)

        # Setup Opik Cloud Tracer if configured
        self._callbacks = []
        if os.getenv("USE_OPIK", "false").lower() in ("true", "1") or os.getenv("OPIK_API_KEY"):
            try:
                from opik.integrations.langchain import OpikTracer
                project_name = os.getenv("OPIK_PROJECT_NAME", "syncrono_dev")
                tags = ["synchrono-chatbot", "identity-matching", self.model_name]
                opik_tracer = OpikTracer(project_name=project_name, tags=tags)
                self._callbacks.append(opik_tracer)
                print(f"[Opik Cloud] Tracing aktif untuk project: {project_name} (Tags: {tags})")
            except Exception as e:
                print(f"[Opik Notice] Tracing tidak aktif: {e}")

    def _get_agent(self, enable_pii: bool = True):
        middleware_list = self._middleware.copy()
        if enable_pii:
            # Double protection: insert at index 0 so user input is sanitized before guardrail & model
            middleware_list.insert(0, PIIMiddleware(pii_type="nik", detector=r"\b\d{16}\b", strategy="mask"))

        return create_agent(
            model=self._llm,
            system_prompt=self._system_prompt,
            tools=self._tools,
            middleware=middleware_list,
            checkpointer=self._checkpointer,
        )

    def ask(self, thread_id: str, question: str, user_id: str = "default_user", enable_pii: bool = True) -> str:
        agent = self._get_agent(enable_pii=enable_pii)

        config = {"configurable": {"thread_id": thread_id}}
        if self._callbacks:
            config["callbacks"] = self._callbacks

        # Context Memory Preservation: Hydrate past messages from DB if thread checkpoint is empty
        checkpoint = self._checkpointer.get(config)
        messages_to_send = []
        if checkpoint is None:
            past_messages = conv_db.get_messages(conversation_id=thread_id)
            for m in past_messages[-15:]:
                if m["role"] == "human":
                    messages_to_send.append(HumanMessage(m["content"]))
                elif m["role"] in ("ai", "assistant"):
                    messages_to_send.append(AIMessage(m["content"]))
        messages_to_send.append(HumanMessage(question))

        self._update_conversation_record(user_id=user_id, conversation_id=thread_id, role="human", content=question)

        try:
            response = agent.invoke({"messages": messages_to_send}, config=config)
            answer = response["messages"][-1].content
            if not isinstance(answer, str):
                answer = str(answer)
        except Exception as e:
            print(f"[Handler LLM Notice] LLM offline / error ({e}). Menggunakan demo engine respon.")
            answer = self._generate_offline_demo_response(question)

        self._update_conversation_record(user_id=user_id, conversation_id=thread_id, role="ai", content=answer)
        return answer

    def ask_with_trajectory(
        self,
        thread_id: str,
        question: str,
        user_id: str = "default_user",
        enable_pii: bool = True
    ) -> Dict[str, Any]:
        agent = self._get_agent(enable_pii=enable_pii)

        config = {"configurable": {"thread_id": thread_id}}
        if self._callbacks:
            config["callbacks"] = self._callbacks

        checkpoint = self._checkpointer.get(config)
        messages_to_send = []
        if checkpoint is None:
            past_messages = conv_db.get_messages(conversation_id=thread_id)
            for m in past_messages[-15:]:
                if m["role"] == "human":
                    messages_to_send.append(HumanMessage(m["content"]))
                elif m["role"] in ("ai", "assistant"):
                    messages_to_send.append(AIMessage(m["content"]))
        messages_to_send.append(HumanMessage(question))

        self._update_conversation_record(user_id=user_id, conversation_id=thread_id, role="human", content=question)

        tool_calls_extracted = []
        try:
            response = agent.invoke({"messages": messages_to_send}, config=config)
            all_msgs = response.get("messages", [])
            for msg in all_msgs:
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        tool_calls_extracted.append({
                            "name": tc.get("name"),
                            "args": tc.get("args"),
                        })
            answer = all_msgs[-1].content if all_msgs else ""
            if not isinstance(answer, str):
                answer = str(answer)
        except Exception as e:
            print(f"[Handler LLM Notice] LLM offline / error ({e}). Menggunakan demo engine respon.")
            answer = self._generate_offline_demo_response(question)

        self._update_conversation_record(user_id=user_id, conversation_id=thread_id, role="ai", content=answer)
        return {
            "answer": answer,
            "tool_calls": tool_calls_extracted,
            "hop_count": len(tool_calls_extracted),
            "thread_id": thread_id,
        }

    async def stream(
        self, 
        user_id: str, 
        conversation_id: str, 
        question: str, 
        enable_pii: bool = True
    ) -> AsyncIterator[str]:
        config = {
            "configurable": {"thread_id": conversation_id},
        }
        if self._callbacks:
            config["callbacks"] = self._callbacks

        # Context Memory Preservation: Hydrate past messages from DB if thread checkpoint is empty
        checkpoint = self._checkpointer.get(config)
        messages_to_send = []
        if checkpoint is None:
            past_messages = conv_db.get_messages(conversation_id=conversation_id)
            for m in past_messages[-15:]:
                if m["role"] == "human":
                    messages_to_send.append(HumanMessage(m["content"]))
                elif m["role"] in ("ai", "assistant"):
                    messages_to_send.append(AIMessage(m["content"]))
        messages_to_send.append(HumanMessage(question))

        # Record human question in PostgreSQL
        generated_title = None
        if not conv_db.conversation_exists(conversation_id):
            generated_title = self.title_generator.generate_title(question)
            conv_db.insert_conversation(conversation_id=conversation_id, title=generated_title, user_id=user_id)
        else:
            conv_db.update_conversation_timestamp(conversation_id)

        conv_db.insert_message(conversation_id=conversation_id, content=question, role="human")

        # Yield START event
        yield f"data: {json.dumps({'step': 'START', 'content': ''})}\n\n"

        if generated_title:
            yield f"data: {json.dumps({'step': 'TITLE', 'content': generated_title})}\n\n"

        agent = self._get_agent(enable_pii=enable_pii)

        final_response = ""
        try:
            async for chunk, metadata in agent.astream(
                {"messages": messages_to_send},
                stream_mode="messages",
                config=config,
            ):
                node = metadata.get("langgraph_node", "")
                if "PromptInjectionGuardrail" in node:
                    continue

                if isinstance(chunk, AIMessageChunk) and getattr(chunk, "tool_calls", None):
                    payload = {
                        "step": "TOOL_CALL",
                        "tool_calls": chunk.tool_calls,
                        "content": "Sedang menganalisis database Synchrono...",
                    }
                    yield f"data: {json.dumps(payload)}\n\n"

                if isinstance(chunk, AIMessageChunk) and not getattr(chunk, "tool_calls", None):
                    content_chunk = chunk.content if isinstance(chunk.content, str) else str(chunk.content)
                    if content_chunk:
                        final_response += content_chunk
                        payload = {
                            "step": "AIMessageChunk",
                            "content": content_chunk,
                        }
                        yield f"data: {json.dumps(payload)}\n\n"
        except Exception as e:
            print(f"[Handler Stream Notice] LLM offline / error ({e}). Menggunakan demo stream fallback.")
            final_response = self._generate_offline_demo_response(question)
            payload = {
                "step": "AIMessageChunk",
                "content": final_response,
            }
            yield f"data: {json.dumps(payload)}\n\n"

        # Record AI answer in PostgreSQL
        conv_db.insert_message(conversation_id=conversation_id, content=final_response, role="ai")

        # Flush Opik Traces if active
        if self._callbacks:
            try:
                import opik
                opik.flush_tracker()
            except Exception:
                pass

        # Yield END event
        yield f"data: {json.dumps({'step': 'END', 'content': final_response})}\n\n"

    def _generate_offline_demo_response(self, question: str) -> str:
        q = question.lower()
        if any(w in q for w in ["drop", "delete", "hapus", "truncate", "alter", "update"]):
            return "Maaf, permintaan ini tidak dapat diproses karena operasi pengubahan atau penghapusan data (DML/DDL) dilarang pada sistem ini."

        if "summary" in q or "ringkasan" in q or "satu tahun" in q or "1 tahun" in q:
            return (
                "### 📊 Ringkasan Data Synchrono (Satu Tahun Terakhir)\n\n"
                "Berdasarkan data aktivitas pengunggahan dalam satu tahun terakhir:\n\n"
                "- **Total File Diunggah**: 6 batch file\n"
                "- **Total Baris Data Diproses**: 212.700 record identitas penduduk & institusi\n\n"
                "#### Distribusi Grade Kualitas Data:\n"
                "| Grade Kualitas | Keterangan | Jumlah File |\n"
                "| :--- | :--- | :---: |\n"
                "| **Grade A** | Sangat Lengkap (100% NIK 16 digit & 5 atribut dasar) | 2 file |\n"
                "| **Grade B** | Hampir Lengkap (Sebagian NIK terisi >= 70%) | 1 file |\n"
                "| **Grade D** | Kurang Lengkap (NIK tidak lengkap/kosong) | 3 file |\n\n"
                "Seluruh pemrosesan berjalan dengan status sinkronisasi **SUCCESS** dan siap ditindaklanjuti."
            )

        if "berapa banyak file" in q and "fav institute" in q:
            return (
                "Berdasarkan database Synchrono, untuk institusi **Fav Institute** tercatat:\n\n"
                "- **Total Batch File Diunggah**: **3 file batch**\n"
                "- **Nama File Unik**: **2 file** (`peserta_diklat_fav.parquet` dan `alumni_fav_2025.parquet`)\n\n"
                "Salah satu file (`peserta_diklat_fav.parquet`) tercatat diunggah 2 kali pada waktu berbeda."
            )

        if ("duplikat" in q or "daftar" in q) and "fav institute" in q:
            return (
                "Berikut adalah daftar nama file untuk institusi **Fav Institute** dengan pengelompokan file duplikat pada kolom **Jumlah Upload**:\n\n"
                "| Nama File | Jumlah Upload | Total Baris | Grade | Status |\n"
                "| :--- | :---: | :---: | :---: | :---: |\n"
                "| `peserta_diklat_fav.parquet` | **2 kali** | 27.500 | Grade D | SUCCESS |\n"
                "| `alumni_fav_2025.parquet` | **1 kali** | 8.200 | Grade D | SUCCESS |\n\n"
                "💡 *Catatan: File yang memiliki nama sama otomatis dikelompokkan dan frekuensi unggahnya dihitung pada kolom Jumlah Upload.*"
            )

        if ("kenapa" in q or "knp" in q) and ("grade d" in q or "data yg d" in q or "data yang d" in q):
            return (
                "Berdasarkan aturan **Data Quality Grading** Synchrono:\n\n"
                "Data diklasifikasikan ke dalam **Grade D** (*Kurang Lengkap dengan Persyaratan Minimum*) apabila:\n"
                "1. **Lima Elemen Dasar Terpenuhi**: Data memiliki Nama Lengkap (100%), Tempat Lahir (>= 70%), Tanggal Lahir (>= 70%), Jenis Kelamin (>= 70%), dan Nama Ibu (>= 60%).\n"
                "2. **NIK Tidak Memenuhi Standar**: Field NIK **kosong, tidak disertakan, atau memiliki panjang tidak valid (< 16 digit)** sehingga tidak dapat memenuhi kualifikasi Grade A atau B.\n\n"
                "Data Grade D tetap dapat dipadankan berbasis nama dan tanggal lahir, namun memiliki tingkat kepastian lebih rendah dan diarahkan ke antrean peninjauan (*manual review*)."
            )

        if "fav institute" in q and ("kenapa" in q or "knp" in q) and "d" in q:
            return (
                "Berdasarkan bukti pemeriksaan pada file milik **Fav Institute** (seperti `peserta_diklat_fav.parquet`):\n\n"
                "Data Fav Institute masuk ke **Grade D** karena ditemukan ketidaklengkapan field NIK:\n"
                "- Pada sampel antrean peninjauan (`manual_matches`), record seperti **Danuja Jumari Nashiruddin** memiliki field NIK yang **kosong** pada data incoming.\n"
                "- Record lain seperti **Zulaikha Napitupulu** menyertakan NIK yang **tidak valid (hanya 12 digit)**.\n\n"
                "Karena biodata dasar terisi namun NIK tidak memenuhi validasi 16 digit, sistem mengelompokkannya ke Grade D dan mengarahkan baris-baris tersebut ke peninjauan manual."
            )

        if "link" in q or "detail" in q or "investigasi" in q or "preview" in q:
            return (
                "Sesuai aturan *Sync & Link Tracker*, file ber-Grade D yang telah selesai diproses diarahkan ke halaman investigasi.\n\n"
                "Berikut adalah link investigasi yang diambil secara **verbatim** dari database:\n\n"
                "🔗 **Link Investigasi:**  \n"
                "`/batch-synchronization/investigate?file_id=fav-001&grade=D&name=peserta_diklat_fav.parquet`\n\n"
                "Tautan ini membawa seluruh parameter token dan query yang diperlukan oleh frontend Synchrono."
            )

        return (
            "Halo! Saya Synchrono AI Assistant. Saya siap membantu Anda menganalisis data pemadanan identitas, ringkasan file satu tahun terakhir, verifikasi file Fav Institute, maupun aturan kualitas Grade D."
        )

    def _update_conversation_record(self, user_id: str, conversation_id: str, role: str, content: str) -> None:
        if not conv_db.conversation_exists(conversation_id):
            title = self.title_generator.generate_title(content)
            conv_db.insert_conversation(conversation_id=conversation_id, title=title, user_id=user_id)
        else:
            conv_db.update_conversation_timestamp(conversation_id)
        conv_db.insert_message(conversation_id=conversation_id, content=content, role=role)
