import os
import re
import json
from time import perf_counter
from uuid import uuid4
from contextlib import contextmanager, asynccontextmanager
from typing import AsyncIterator, Optional, List, Dict, Any
from dotenv import load_dotenv
from loguru import logger
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from langchain.messages import SystemMessage, HumanMessage, AIMessage, AIMessageChunk
from langchain.agents import create_agent
from langchain.agents.middleware import TodoListMiddleware, ToolRetryMiddleware, SummarizationMiddleware
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from src.prompts import SYNCHRONO_AGENT_SYSTEM_PROMPT, TITLE_GENERATOR_PROMPT
from src.tools import (
    query_metrics,
    run_query,
    get_table_names,
    get_table_detail,
    load_skills,
    get_grading_status_summary,
    get_matching_status_summary,
    get_failed_matching_jobs,
    get_file_status,
    get_latest_grading_jobs,
    get_batch_status_summary,
    get_anomaly_summary,
)
from src.middlewares import PromptInjectionGuardrail, PIIMiddleware
from src.middlewares.pii import PIIStreamSanitizer
from src.databases.internal.config import INTERNAL_DB_URL, SessionLocal
from src.databases.internal.models import Conversation, Message, User
from src.semantic_cache import SemanticCache
from src.observability.file_tracer import LocalFileTracer
from src.observability.answer_audit import record_answer_audit
from src.messages import (
    DOCUMENT_NOT_FOUND_MESSAGE,
    DOCUMENT_SYNTHESIS_FAILED_MESSAGE,
    FAQ_NOT_FOUND_MESSAGE,
    FAQ_SYNTHESIS_FAILED_MESSAGE,
    GENERIC_FALLBACK_MESSAGE,
    OUT_OF_SCOPE_MESSAGE,
)
from src.knowledge.question_routing import (
    is_document_content_question,
    is_live_data_question,
    is_out_of_scope_public_service_question,
    is_platform_faq_question,
)

load_dotenv()


def get_postgres_saver_uri() -> str:
    """Normalize SQLAlchemy PostgreSQL URL into a standard libpq/psycopg connection string."""
    url = str(INTERNAL_DB_URL)
    if url.startswith("postgresql+"):
        url = re.sub(r"^postgresql\+[a-zA-Z0-9_]+://", "postgresql://", url)
    elif url.startswith("postgres+"):
        url = re.sub(r"^postgres\+[a-zA-Z0-9_]+://", "postgresql://", url)
    return url


def _get_default_embedding():
    embedding_provider = os.getenv("EMBEDDING_PROVIDER", "ollama").lower()
    if embedding_provider == "openai":
        try:
            from langchain_openai import OpenAIEmbeddings
            # EMBEDDING_BASE_URL / EMBEDDING_API_KEY point at an OpenAI-compatible
            # embedding gateway (e.g. ollama-proxies) separate from the chat model.
            # Such gateways take text only, so the client must not send token ids
            # (check_embedding_ctx_length), which only api.openai.com accepts.
            return OpenAIEmbeddings(
                model=os.getenv("OPENAI_EMBEDDING_MODEL")
                or os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
                api_key=os.getenv("EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY"),
                base_url=os.getenv("EMBEDDING_BASE_URL") or os.getenv("OPENAI_BASE_URL"),
                check_embedding_ctx_length=False,
            )
        except Exception as e:
            logger.warning(f"Failed to initialize OpenAIEmbeddings: {e}")

    try:
        from langchain_ollama import OllamaEmbeddings
        return OllamaEmbeddings(
            base_url=os.getenv("OLLAMA_LOCAL_BASE_URL") or os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434",
            model=os.getenv("EMBEDDING_MODEL", "qwen3-embedding:8b"),
        )
    except Exception as e:
        logger.warning(f"Failed to initialize OllamaEmbeddings: {e}")
        return None


class TitleOutput(BaseModel):
    title: str = Field(description="Conversation title generated from user query in Bahasa Indonesia.")


class TitleGenerator:
    def __init__(self):
        self._model = ChatOpenAI(
            model=os.getenv("OPENAI_MODEL_NAME", "gemma4:31b-cloud"),
            base_url=os.getenv("OPENAI_BASE_URL"),
            api_key=os.getenv("OPENAI_API_KEY", "ollama"),
            temperature=0,
        )
        self._parser = PydanticOutputParser(pydantic_object=TitleOutput)
        self._prompt = PromptTemplate.from_template(
            TITLE_GENERATOR_PROMPT, 
            partial_variables={"format_instructions": self._parser.get_format_instructions()}
        )
        self._chain = self._prompt | self._model | self._parser

    def generate_title(self, question: str, callbacks: Optional[list] = None) -> str:
        try:
            output: TitleOutput = self._chain.invoke(
                {"question": question},
                config={"callbacks": callbacks or []},
            )
            title = output.title.strip()
            return title if title else "New Conversation"
        except Exception as e:
            logger.error(f"Error generating conversation title: {e}")
            return "New Conversation"


class ChatbotHandler:
    def __init__(
        self,
        semantic_cache: Optional[SemanticCache] = None,
        checkpointer: Optional[Any] = None,
        document_cache: Optional[SemanticCache] = None,
    ):
        self._model = ChatOpenAI(
            model=os.getenv("OPENAI_MODEL_NAME", "gemma4:31b-cloud"),
            base_url=os.getenv("OPENAI_BASE_URL"),
            api_key=os.getenv("OPENAI_API_KEY", "ollama"),
            temperature=0,
        )
        self._system_prompt = SystemMessage(SYNCHRONO_AGENT_SYSTEM_PROMPT)
        self._tools = [
            query_metrics,
            get_grading_status_summary,
            get_matching_status_summary,
            get_failed_matching_jobs,
            get_file_status,
            get_latest_grading_jobs,
            get_batch_status_summary,
            get_anomaly_summary,
            run_query,
            get_table_names,
            get_table_detail,
            load_skills,
        ]
        self._middleware = [
            PromptInjectionGuardrail(),
            ToolRetryMiddleware(max_retries=2),
            SummarizationMiddleware(
                model=self._model,
                trigger=("messages", 15),
                keep=("messages", 6)
            ),
            TodoListMiddleware()    
        ]
        self.title_generator = TitleGenerator()
        self._trace_enabled = os.getenv("CHATBOT_FILE_TRACE_ENABLED", "true").lower() in ("true", "1", "yes")
        self._custom_checkpointer = checkpointer

        # Semantic cache with >90% confidence retrieval condition
        if semantic_cache is not None:
            self._semantic_cache = semantic_cache
            self._document_cache = document_cache
        else:
            try:
                self._embedding = _get_default_embedding()
                cache_kwargs = {
                    "embedding": self._embedding,
                    "max_distance": float(os.getenv("SEMANTIC_CACHE_DISTANCE", "0.10")),
                    "min_confidence": float(os.getenv("SEMANTIC_CACHE_MIN_CONFIDENCE", "0.90")),
                }
                self._semantic_cache = SemanticCache(**cache_kwargs)
                self._document_cache = document_cache or SemanticCache(scope="document", **cache_kwargs)
            except Exception as e:
                logger.warning(f"Semantic cache could not be initialized: {e}")
                self._semantic_cache = None
                self._document_cache = None

    @contextmanager
    def _get_checkpointer(self):
        """Context manager yielding PostgresSaver checkpointer with automatic table migration."""
        if self._custom_checkpointer is not None:
            yield self._custom_checkpointer
            return

        postgres_uri = get_postgres_saver_uri()
        try:
            with PostgresSaver.from_conn_string(postgres_uri) as cp:
                cp.setup()
                yield cp
        except Exception as e:
            logger.warning(f"[ChatbotHandler] PostgresSaver unavailable ({e}). Falling back to MemorySaver.")
            from langgraph.checkpoint.memory import MemorySaver
            yield MemorySaver()

    @asynccontextmanager
    async def _get_async_checkpointer(self):
        """Async context manager yielding AsyncPostgresSaver checkpointer with automatic table migration."""
        if self._custom_checkpointer is not None:
            yield self._custom_checkpointer
            return

        postgres_uri = get_postgres_saver_uri()
        try:
            async with AsyncPostgresSaver.from_conn_string(postgres_uri) as cp:
                await cp.setup()
                yield cp
        except Exception as e:
            logger.warning(f"[ChatbotHandler] AsyncPostgresSaver unavailable ({e}). Falling back to MemorySaver.")
            from langgraph.checkpoint.memory import MemorySaver
            yield MemorySaver()

    @staticmethod
    def _active_document_version() -> int:
        from src.knowledge.document_service import get_active_document_version

        return int(get_active_document_version())

    def _lookup_document_cache(self, question: str, trace: Optional[LocalFileTracer]) -> tuple[bool, Optional[str]]:
        if self._document_cache is None:
            return False, None
        try:
            if self._active_document_version() <= 0:
                return False, None
        except Exception as e:
            logger.warning(f"[DocumentCache] Active document version check failed: {e}")
            return False, None
        try:
            cached_answer = self._document_cache.get(question)
        except Exception as e:
            logger.error(f"[DocumentCache] Error checking cache: {e}")
            if trace:
                trace.log_event("document_cache.failed", error_type=type(e).__name__)
            return True, None
        if trace:
            trace.log_event(
                "document_cache.hit" if cached_answer is not None else "document_cache.miss",
                confidence_threshold=0.90,
            )
        return True, cached_answer

    def _store_document_cache(
        self,
        question: str,
        answer: str,
        chunks: list[dict[str, str | float]],
        trace: Optional[LocalFileTracer],
    ) -> None:
        if self._document_cache is None:
            return
        try:
            self._document_cache.set(question, answer, chunks)
            if trace:
                trace.log_event(
                    "document_cache.set",
                    source_count=len({str(chunk.get("source", "")) for chunk in chunks}),
                )
        except Exception as e:
            logger.error(f"[DocumentCache] Error saving document answer: {e}")
            if trace:
                trace.log_event("document_cache.set_failed", error_type=type(e).__name__)

    @staticmethod
    def _top_retrieval_score(chunks: list[dict[str, Any]]) -> Optional[float]:
        scores = []
        for chunk in chunks:
            try:
                scores.append(float(chunk.get("score")))
            except (TypeError, ValueError):
                continue
        return max(scores) if scores else None

    @staticmethod
    def _source_count(chunks: list[dict[str, Any]]) -> int:
        return len({str(chunk.get("source", "")) for chunk in chunks if chunk.get("source")})

    @staticmethod
    def _audit_answer(
        *,
        user_id: str,
        thread_id: str,
        route: str,
        question: str,
        answer: str,
        chunks: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        if os.getenv("CHATBOT_ANSWER_AUDIT_ENABLED", "true").strip().lower() in {"0", "false", "no", "off"}:
            return
        try:
            record_answer_audit(
                user_id=user_id,
                thread_id=thread_id,
                route=route,
                question=question,
                answer=answer,
                retrieval_score=ChatbotHandler._top_retrieval_score(chunks or []),
                source_count=ChatbotHandler._source_count(chunks or []),
            )
        except Exception as exc:
            logger.warning(f"[AnswerAudit] Audit hook failed: {exc}")

    def invoke(self, thread_id: str, question: str, user_id: str = "default_user", enable_pii: bool = True) -> str:
        trace = LocalFileTracer() if self._trace_enabled else None
        started_at = perf_counter()
        callbacks = [trace] if trace else []
        pii_middleware = PIIMiddleware(pii_type="nik", strategy="mask") if enable_pii else None
        if pii_middleware is not None:
            question = pii_middleware.sanitize_text(question)
        faq_route = is_platform_faq_question(question)
        document_route = is_document_content_question(question)
        if trace:
            route = "faq" if faq_route else "document" if document_route else "agent"
            trace.log_event("chat.request_started", route=route, pii_enabled=enable_pii, question=question)

        # Only stable, approved platform FAQs are eligible for direct FAQ cache.
        if is_out_of_scope_public_service_question(question):
            answer = OUT_OF_SCOPE_MESSAGE
            if trace:
                trace.log_event("chat.request_rejected", reason="out_of_scope", duration_ms=round((perf_counter() - started_at) * 1000, 2), question=question, answer=answer)
            return answer

        # The Valkey semantic cache is reserved exclusively for approved FAQ documents.
        faq_question = is_platform_faq_question(question)
        if faq_question and self._semantic_cache is not None:
            try:
                cached_answer = self._semantic_cache.get(question)
                if cached_answer is not None:
                    logger.info(f"[SemanticCache] Serving cached answer for invoke (>90% conf)")
                    if pii_middleware:
                        cached_answer = pii_middleware.sanitize_text(cached_answer)
                    if trace:
                        trace.log_event("faq_cache.hit", threshold_confidence=0.90)
                        trace.log_event("chat.request_completed", route="faq_cache", duration_ms=round((perf_counter() - started_at) * 1000, 2), answer=cached_answer)
                    return cached_answer
                if trace:
                    trace.log_event("faq_cache.miss", threshold_confidence=0.90)
            except Exception as e:
                logger.error(f"[SemanticCache] Error checking cache in invoke: {e}")

        if faq_question:
            if trace:
                trace.log_event("faq.retrieval_started")
            faq_chunks = self._lookup_platform_faq_chunks(question)
            if trace:
                trace.log_event(
                    "faq.retrieval_completed",
                    chunk_count=len(faq_chunks),
                    sources=sorted({str(chunk.get("source", "")) for chunk in faq_chunks}),
                )
            if not faq_chunks:
                answer = FAQ_NOT_FOUND_MESSAGE
                if trace:
                    trace.log_event("chat.request_completed", route="faq_not_found", duration_ms=round((perf_counter() - started_at) * 1000, 2), answer=answer)
                return answer
            faq_answer = self._synthesize_faq_answer(question, faq_chunks, pii_middleware, callbacks)
            if faq_answer is None:
                answer = FAQ_SYNTHESIS_FAILED_MESSAGE
                if trace:
                    trace.log_event("chat.request_failed", route="faq_synthesis", duration_ms=round((perf_counter() - started_at) * 1000, 2), answer=answer)
                return answer
            if pii_middleware:
                faq_answer = pii_middleware.sanitize_text(faq_answer)
            if self._semantic_cache is not None:
                try:
                    self._semantic_cache.set(question, faq_answer)
                    if trace:
                        trace.log_event("faq_cache.set", source_count=len({str(chunk.get("source", "")) for chunk in faq_chunks}))
                except Exception as e:
                    logger.error(f"[FAQCache] Error saving FAQ answer in invoke: {e}")
            self._audit_answer(
                user_id=user_id,
                thread_id=thread_id,
                route="faq_synthesized",
                question=question,
                answer=faq_answer,
                chunks=faq_chunks,
            )
            if trace:
                trace.log_event("chat.request_completed", route="faq_synthesized", duration_ms=round((perf_counter() - started_at) * 1000, 2), answer=faq_answer)
            return faq_answer

        document_question = is_document_content_question(question)
        if document_question or not is_live_data_question(question):
            document_cache_enabled, cached_document_answer = self._lookup_document_cache(question, trace)
            if cached_document_answer is not None:
                logger.info("[DocumentCache] Serving cached document answer for invoke (>90% conf)")
                if pii_middleware:
                    cached_document_answer = pii_middleware.sanitize_text(cached_document_answer)
                if trace:
                    trace.log_event("chat.request_completed", route="document_cache", duration_ms=round((perf_counter() - started_at) * 1000, 2), answer=cached_document_answer)
                return cached_document_answer
            if trace:
                trace.log_event("document.retrieval_started")
            document_chunks = self._lookup_platform_document_chunks(question)
            if trace:
                trace.log_event(
                    "document.retrieval_completed",
                    chunk_count=len(document_chunks),
                    sources=sorted({str(chunk.get("source", "")) for chunk in document_chunks}),
                    top_score=max((float(chunk.get("score", 0.0)) for chunk in document_chunks), default=None),
                )
            if document_chunks:
                document_answer = self._synthesize_document_answer(
                    question, document_chunks, pii_middleware, callbacks
                )
                if document_answer is not None:
                    if pii_middleware:
                        document_answer = pii_middleware.sanitize_text(document_answer)
                    if document_cache_enabled:
                        self._store_document_cache(question, document_answer, document_chunks, trace)
                    self._audit_answer(
                        user_id=user_id,
                        thread_id=thread_id,
                        route="document_synthesized",
                        question=question,
                        answer=document_answer,
                        chunks=document_chunks,
                    )
                    if trace:
                        trace.log_event("chat.request_completed", route="document_synthesized", duration_ms=round((perf_counter() - started_at) * 1000, 2), answer=document_answer)
                    return document_answer
            if document_question:
                answer = DOCUMENT_NOT_FOUND_MESSAGE
                if trace:
                    trace.log_event("chat.request_completed", route="document_not_found", duration_ms=round((perf_counter() - started_at) * 1000, 2), answer=answer)
                return answer

        # 2. Run agent execution with PostgresSaver checkpointer
        _current_middleware = self._middleware.copy()
        if pii_middleware:
            _current_middleware.append(pii_middleware)

        def run_agent():
            with self._get_checkpointer() as checkpointer:
                agent = create_agent(
                    model=self._model,
                    tools=self._tools,
                    system_prompt=self._system_prompt,
                    checkpointer=checkpointer,
                    middleware=_current_middleware,
                )
                config = {
                    "configurable": {"thread_id": thread_id, "user_id": user_id},
                    "callbacks": callbacks,
                }
                return agent.invoke({"messages": [HumanMessage(content=question)]}, config=config)

        if trace:
            with trace.bind():
                response = run_agent()
        else:
            response = run_agent()
        answer = response["messages"][-1].content
        if pii_middleware:
            answer = pii_middleware.sanitize_text(answer)

        self._audit_answer(
            user_id=user_id,
            thread_id=thread_id,
            route="agent",
            question=question,
            answer=answer,
        )
        if trace:
            trace.log_event("chat.request_completed", route="agent", duration_ms=round((perf_counter() - started_at) * 1000, 2), answer=answer)
        return answer

    @staticmethod
    def _lookup_platform_faq_chunks(question: str, k: int = 3) -> list[dict[str, str | float]]:
        """Retrieve relevant curated FAQ chunks to ground FAQ answer generation."""
        try:
            from src.knowledge.faq_service import retrieve_platform_faq_chunks

            return retrieve_platform_faq_chunks(question, k=k)
        except Exception as e:
            logger.exception(f"[FAQ] FAQ chunk retrieval failed: {e}")
            return []

    def _synthesize_faq_answer(
        self,
        question: str,
        chunks: list[dict[str, str | float]],
        pii_middleware: Optional[PIIMiddleware] = None,
        callbacks: Optional[list] = None,
    ) -> Optional[str]:
        def safe(value: object) -> str:
            text = str(value)
            return pii_middleware.sanitize_text(text) if pii_middleware else text

        context = "\n\n---\n\n".join(
            f"Source: {safe(chunk['source'])}\nFAQ question: {safe(chunk['matched_question'])}\nFAQ answer: {safe(chunk['answer'])}"
            for chunk in chunks
        )
        try:
            response = self._model.invoke(
                [
                    SystemMessage(
                        "You answer questions about the Synchrono identity-matching platform using ONLY the supplied FAQ chunks. "
                        "Synthesize the relevant chunks into a concise, clear Indonesian answer. Do not add facts, rules, steps, "
                        "or claims that are not present in the chunks. If a point is not covered, say the FAQ does not specify it. "
                        "Keep the distinction that AI explains/recommends while rules and operators decide statuses. Do not expose raw personal data."
                    ),
                    HumanMessage(
                        content=f"User question:\n{question}\n\nRetrieved approved FAQ chunks:\n{context}"
                    ),
                ],
                config={"callbacks": callbacks or []},
            )
            answer = response.content if isinstance(response.content, str) else str(response.content)
            sources = ", ".join(sorted({str(chunk["source"]) for chunk in chunks}))
            return f"{answer.strip()}\n\nSumber FAQ: {sources}"
        except Exception as e:
            logger.exception(f"[FAQ] LLM could not synthesize a grounded answer: {e}")
            return None

    @staticmethod
    def _lookup_platform_document_chunks(question: str, k: int = 4) -> list[dict[str, str | int | float]]:
        """Retrieve the most relevant chunks from the active general-document snapshot."""
        try:
            from src.knowledge.document_service import retrieve_platform_document_chunks

            return retrieve_platform_document_chunks(question, k=k)
        except Exception as e:
            logger.exception(f"[Document] Document chunk retrieval failed: {e}")
            return []

    def _synthesize_document_answer(
        self,
        question: str,
        chunks: list[dict[str, str | int | float]],
        pii_middleware: Optional[PIIMiddleware] = None,
        callbacks: Optional[list] = None,
    ) -> Optional[str]:
        def safe(value: object) -> str:
            text = str(value)
            return pii_middleware.sanitize_text(text) if pii_middleware else text

        context = "\n\n---\n\n".join(
            f"Source: {safe(chunk['source'])} (chunk {safe(chunk.get('chunk', 0))})\n{safe(chunk['content'])}"
            for chunk in chunks
        )
        try:
            response = self._model.invoke(
                [
                    SystemMessage(
                        "You answer questions about uploaded Synchrono documents using ONLY the supplied document chunks. "
                        "Synthesize the relevant chunks into a concise, clear Indonesian answer. Do not add facts, rules, steps, "
                        "or claims that are not present in the chunks. If the chunks do not cover a point, say the document does "
                        "not specify it. Never invent policies, procedures, links, personal data, or database details. "
                        "Mention the source file name when it helps traceability."
                    ),
                    HumanMessage(
                        content=f"User question:\n{question}\n\nRetrieved document chunks:\n{context}"
                    ),
                ],
                config={"callbacks": callbacks or []},
            )
            answer = response.content if isinstance(response.content, str) else str(response.content)
            sources = ", ".join(sorted({str(chunk["source"]) for chunk in chunks}))
            return f"{answer.strip()}\n\nSumber dokumen: {sources}"
        except Exception as e:
            logger.exception(f"[Document] LLM could not synthesize a grounded answer: {e}")
            return None

    async def stream(self, user_id: str, conversation_id: str, question: str, enable_pii: bool = True):
        trace = LocalFileTracer() if self._trace_enabled else None
        started_at = perf_counter()
        callbacks = [trace] if trace else []
        pii_middleware = PIIMiddleware(pii_type="nik", strategy="mask") if enable_pii else None
        if pii_middleware is not None:
            # Sanitize before title generation, database writes, cache lookup, and agent input.
            question = pii_middleware.sanitize_text(question)

        if is_out_of_scope_public_service_question(question):
            out_of_scope_answer = OUT_OF_SCOPE_MESSAGE
            if trace:
                trace.log_event("chat.request_rejected", reason="out_of_scope", question=question, answer=out_of_scope_answer)
            yield f"data: {json.dumps({'step': 'START', 'content': ''})}\n\n"
            yield f"data: {json.dumps({'step': 'AIMessageChunk', 'content': out_of_scope_answer})}\n\n"
            yield f"data: {json.dumps({'step': 'END', 'content': ''})}\n\n"
            if trace:
                trace.log_event("chat.request_completed", route="out_of_scope", duration_ms=round((perf_counter() - started_at) * 1000, 2), answer=out_of_scope_answer)
            return

        faq_question = is_platform_faq_question(question)
        document_question = is_document_content_question(question)
        if trace:
            route = "faq" if faq_question else "document" if document_question else "agent"
            trace.log_event("chat.request_started", route=route, thread_id=conversation_id, pii_enabled=enable_pii, question=question)
        # Signal immediately so clients see progress while persistence or first-time FAQ retrieval runs.
        yield f"data: {json.dumps({'step': 'START', 'content': ''})}\n\n"

        generated_title = None
        try:
            db = SessionLocal()
            conv = db.query(Conversation).filter_by(id=conversation_id).first()
            if not conv:
                if db.get(User, user_id) is None:
                    db.add(User(id=user_id))
                    db.flush()
                generated_title = question.strip()[:80] if faq_question else self.title_generator.generate_title(question, callbacks=callbacks)
                conv = Conversation(
                    id=conversation_id, 
                    user_id=user_id, 
                    thread_id=conversation_id,
                    title=generated_title
                )
                db.add(conv)
                db.commit()

            message = Message(
                conversation_id=conversation_id,
                role="user",
                content=question
            )
            db.add(message)
            db.commit()
        except Exception as e:
            logger.error(f"Error creating conversation: {e}")
        finally:
            try:
                db.close()
            except Exception:
                pass

        # 1. Check semantic cache (>90% confidence condition)
        cached_answer = None
        cache_route = None
        document_cache_enabled = False
        if faq_question and self._semantic_cache is not None:
            try:
                cached_answer = self._semantic_cache.get(question)
                if cached_answer is not None:
                    cache_route = "faq_cache"
                if trace:
                    trace.log_event("faq_cache.hit" if cached_answer is not None else "faq_cache.miss", confidence_threshold=0.90)
            except Exception as e:
                logger.error(f"[SemanticCache] Error reading cache in stream: {e}")
                if trace:
                    trace.log_event("faq_cache.failed", error_type=type(e).__name__)

        if (
            cached_answer is None
            and not faq_question
            and (document_question or not is_live_data_question(question))
        ):
            document_cache_enabled, cached_answer = self._lookup_document_cache(question, trace)
            if cached_answer is not None:
                cache_route = "document_cache"

        if cached_answer is not None:
            logger.info(f"[SemanticCache] Serving cached answer in stream (>90% conf)")
            if pii_middleware is not None:
                cached_answer = pii_middleware.sanitize_text(cached_answer)

            # Cache hits bypass normal agent execution, so persist the turn into
            # the same LangGraph message state/checkpointer without invoking the model.
            try:
                async with self._get_async_checkpointer() as checkpointer:
                    cached_turn_agent = create_agent(
                        model=self._model,
                        tools=self._tools,
                        system_prompt=self._system_prompt,
                        middleware=self._middleware + ([pii_middleware] if pii_middleware else []),
                        checkpointer=checkpointer,
                    )
                    await cached_turn_agent.aupdate_state(
                        {"configurable": {"thread_id": conversation_id, "user_id": user_id}},
                        {
                            "messages": [
                                HumanMessage(content=question),
                                AIMessage(content=cached_answer),
                            ]
                        },
                    )
            except Exception as e:
                logger.error(f"[SemanticCache] Failed to checkpoint cached turn: {e}")

            if generated_title:
                yield f"data: {json.dumps({'step': 'TITLE', 'content': generated_title})}\n\n"
            yield f"data: {json.dumps({'step': 'AIMessageChunk', 'content': cached_answer})}\n\n"
            yield f"data: {json.dumps({'step': 'END', 'content': ''})}\n\n"

            try:
                db = SessionLocal()
                message = Message(
                    conversation_id=conversation_id,
                    role="ai",
                    content=cached_answer
                )
                db.add(message)
                db.commit()
            except Exception as e:
                logger.error(f"Error saving cached message: {e}")
            finally:
                try:
                    db.close()
                except Exception:
                    pass
            if trace:
                trace.log_event("chat.request_completed", route=cache_route, duration_ms=round((perf_counter() - started_at) * 1000, 2), answer=cached_answer)
            return

        if faq_question:
            if trace:
                trace.log_event("faq.retrieval_started")
            faq_chunks = await run_in_threadpool(self._lookup_platform_faq_chunks, question)
            if trace:
                trace.log_event(
                    "faq.retrieval_completed",
                    chunk_count=len(faq_chunks),
                    sources=sorted({str(chunk.get("source", "")) for chunk in faq_chunks}),
                    top_score=max((float(chunk.get("score", 0.0)) for chunk in faq_chunks), default=None),
                )
            if not faq_chunks:
                faq_answer = FAQ_NOT_FOUND_MESSAGE
                if trace:
                    trace.log_event("faq.not_found")
            else:
                if trace:
                    with trace.bind():
                        faq_answer = await run_in_threadpool(self._synthesize_faq_answer, question, faq_chunks, pii_middleware, callbacks)
                else:
                    faq_answer = await run_in_threadpool(self._synthesize_faq_answer, question, faq_chunks, pii_middleware, callbacks)
                if faq_answer is None:
                    faq_answer = FAQ_SYNTHESIS_FAILED_MESSAGE
                    if trace:
                        trace.log_event("faq.synthesis_failed")
                if pii_middleware is not None:
                    faq_answer = pii_middleware.sanitize_text(faq_answer)
            if faq_chunks and self._semantic_cache is not None and "belum dapat merangkai jawaban" not in faq_answer:
                try:
                    self._semantic_cache.set(question, faq_answer)
                    if trace:
                        trace.log_event("faq_cache.set", source_count=len({str(chunk.get("source", "")) for chunk in faq_chunks}))
                except Exception as e:
                    logger.error(f"[FAQCache] Error saving direct FAQ answer: {e}")
                    if trace:
                        trace.log_event("faq_cache.set_failed", error_type=type(e).__name__)

            if faq_chunks and faq_answer not in {
                FAQ_NOT_FOUND_MESSAGE,
                FAQ_SYNTHESIS_FAILED_MESSAGE,
            }:
                self._audit_answer(
                    user_id=user_id,
                    thread_id=conversation_id,
                    route="faq_synthesized",
                    question=question,
                    answer=faq_answer,
                    chunks=faq_chunks,
                )
            try:
                async with self._get_async_checkpointer() as checkpointer:
                    faq_agent = create_agent(
                        model=self._model,
                        tools=self._tools,
                        system_prompt=self._system_prompt,
                        middleware=self._middleware + ([pii_middleware] if pii_middleware else []),
                        checkpointer=checkpointer,
                    )
                    await faq_agent.aupdate_state(
                        {"configurable": {"thread_id": conversation_id, "user_id": user_id}},
                        {"messages": [HumanMessage(question), AIMessage(content=faq_answer)]},
                    )
            except Exception as e:
                logger.error(f"[FAQ] Failed to checkpoint direct FAQ answer: {e}")

            if generated_title:
                yield f"data: {json.dumps({'step': 'TITLE', 'content': generated_title})}\n\n"
            yield f"data: {json.dumps({'step': 'AIMessageChunk', 'content': faq_answer})}\n\n"
            yield f"data: {json.dumps({'step': 'END', 'content': ''})}\n\n"
            try:
                db = SessionLocal()
                db.add(Message(conversation_id=conversation_id, role="ai", content=faq_answer))
                db.commit()
            except Exception as e:
                logger.error(f"Error saving direct FAQ message: {e}")
            finally:
                try:
                    db.close()
                except Exception:
                    pass
            if trace:
                trace.log_event("chat.request_completed", route="faq_synthesized", duration_ms=round((perf_counter() - started_at) * 1000, 2), answer=faq_answer)
            return

        if document_question or not is_live_data_question(question):
            if trace:
                trace.log_event("document.retrieval_started")
            document_chunks = await run_in_threadpool(self._lookup_platform_document_chunks, question)
            if trace:
                trace.log_event(
                    "document.retrieval_completed",
                    chunk_count=len(document_chunks),
                    sources=sorted({str(chunk.get("source", "")) for chunk in document_chunks}),
                    top_score=max((float(chunk.get("score", 0.0)) for chunk in document_chunks), default=None),
                )

            document_answer = None
            if document_chunks:
                if trace:
                    with trace.bind():
                        document_answer = await run_in_threadpool(
                            self._synthesize_document_answer,
                            question,
                            document_chunks,
                            pii_middleware,
                            callbacks,
                        )
                else:
                    document_answer = await run_in_threadpool(
                        self._synthesize_document_answer,
                        question,
                        document_chunks,
                        pii_middleware,
                        callbacks,
                    )
                if document_answer is not None and pii_middleware is not None:
                    document_answer = pii_middleware.sanitize_text(document_answer)
                if document_answer is not None and document_cache_enabled:
                    self._store_document_cache(question, document_answer, document_chunks, trace)

            if document_answer is None and document_question:
                if document_chunks:
                    document_answer = DOCUMENT_SYNTHESIS_FAILED_MESSAGE
                else:
                    document_answer = DOCUMENT_NOT_FOUND_MESSAGE

            if document_answer is not None:
                if document_chunks and document_answer not in {
                    DOCUMENT_NOT_FOUND_MESSAGE,
                    DOCUMENT_SYNTHESIS_FAILED_MESSAGE,
                }:
                    self._audit_answer(
                        user_id=user_id,
                        thread_id=conversation_id,
                        route="document_synthesized",
                        question=question,
                        answer=document_answer,
                        chunks=document_chunks,
                    )
                try:
                    async with self._get_async_checkpointer() as checkpointer:
                        document_agent = create_agent(
                            model=self._model,
                            tools=self._tools,
                            system_prompt=self._system_prompt,
                            middleware=self._middleware + ([pii_middleware] if pii_middleware else []),
                            checkpointer=checkpointer,
                        )
                        await document_agent.aupdate_state(
                            {"configurable": {"thread_id": conversation_id, "user_id": user_id}},
                            {"messages": [HumanMessage(question), AIMessage(content=document_answer)]},
                        )
                except Exception as e:
                    logger.error(f"[Document] Failed to checkpoint direct document answer: {e}")

                if generated_title:
                    yield f"data: {json.dumps({'step': 'TITLE', 'content': generated_title})}\n\n"
                yield f"data: {json.dumps({'step': 'AIMessageChunk', 'content': document_answer})}\n\n"
                yield f"data: {json.dumps({'step': 'END', 'content': ''})}\n\n"
                try:
                    db = SessionLocal()
                    db.add(Message(conversation_id=conversation_id, role="ai", content=document_answer))
                    db.commit()
                except Exception as e:
                    logger.error(f"Error saving document message: {e}")
                finally:
                    try:
                        db.close()
                    except Exception:
                        pass
                if trace:
                    route = "document_synthesized" if document_chunks else "document_not_found"
                    trace.log_event("chat.request_completed", route=route, duration_ms=round((perf_counter() - started_at) * 1000, 2), answer=document_answer)
                return

        # 2. Cache miss: execute agent with AsyncPostgresSaver checkpointer
        _current_middleware = self._middleware.copy()
        if pii_middleware:
            _current_middleware.append(pii_middleware)

        async with self._get_async_checkpointer() as checkpointer:
            _agent = create_agent(
                model=self._model,
                system_prompt=self._system_prompt,
                tools=self._tools,
                middleware=_current_middleware,
                checkpointer=checkpointer
            )
            final_response = ""
            pii_stream_sanitizer = PIIStreamSanitizer(pii_middleware) if pii_middleware else None
            async def traced_agent_stream():
                config = {
                    "configurable": {"thread_id": conversation_id},
                    "callbacks": callbacks,
                    "metadata": {"thread_id": conversation_id},
                }
                if trace is None:
                    async for item in _agent.astream(
                        {"messages": [HumanMessage(question)]},
                        stream_mode="messages",
                        config=config,
                    ):
                        yield item
                else:
                    with trace.bind():
                        async for item in _agent.astream(
                            {"messages": [HumanMessage(question)]},
                            stream_mode="messages",
                            config=config,
                        ):
                            yield item

            async for chunk, metadata in traced_agent_stream():
                if metadata.get("ls_integration") == "langchain_chat_model" and (
                    metadata.get("langgraph_node") == "PromptInjectionGuardrail.before_agent"
                    or metadata.get("langgraph_node") == "SummarizationMiddleware.before_model"
                ):
                    continue

                chunk_text = chunk.text
                is_final_answer_chunk = isinstance(chunk, AIMessageChunk) and not chunk.tool_calls
                if pii_middleware is not None and not is_final_answer_chunk:
                    # Tool/database messages are complete message events; sanitize
                    # them before exposing their content through SSE as well.
                    chunk_text = pii_middleware.sanitize_text(chunk_text)

                data = {
                    "step": chunk.__class__.__name__,
                    "content": chunk_text,
                }

                if isinstance(chunk, AIMessageChunk) and chunk.tool_calls:
                    data["tool_calls"] = (
                        pii_middleware.sanitize_content(chunk.tool_calls)
                        if pii_middleware else chunk.tool_calls
                    )

                if is_final_answer_chunk:
                    if pii_stream_sanitizer:
                        safe_text = pii_stream_sanitizer.feed(chunk_text)
                    else:
                        safe_text = chunk_text
                    final_response += safe_text
                    data["content"] = safe_text

                if data["content"] or data.get("tool_calls"):
                    yield f"data: {json.dumps(data)}\n\n"

            if pii_stream_sanitizer:
                final_tail = pii_stream_sanitizer.feed("", final=True)
                if final_tail:
                    final_response += final_tail
                    yield f"data: {json.dumps({'step': 'AIMessageChunk', 'content': final_tail})}\n\n"

            if not final_response.strip():
                final_response = GENERIC_FALLBACK_MESSAGE
                yield f"data: {json.dumps({'step': 'AIMessageChunk', 'content': final_response})}\n\n"

            end_payload = {
                "step": "END",
                "content": "",
            }
            yield f"data: {json.dumps(end_payload)}\n\n"
            
            if generated_title:
                title_payload = {
                    "step": "TITLE",
                    "content": generated_title
                }
                yield f"data: {json.dumps(title_payload)}\n\n"

            try:
                db = SessionLocal()
                message = Message(
                    conversation_id=conversation_id,
                    role="ai",
                    content=final_response
                )
                db.add(message)
                db.commit()
            except Exception as e:
                logger.error(f"Error saving message: {e}")
            finally:
                try:
                    db.close()
                except Exception:
                    pass

            # Model-generated conversation/database answers are deliberately not cached.
            self._audit_answer(
                user_id=user_id,
                thread_id=conversation_id,
                route="agent",
                question=question,
                answer=final_response,
            )
            if trace:
                trace.log_event("chat.request_completed", route="agent", duration_ms=round((perf_counter() - started_at) * 1000, 2), answer=final_response)
