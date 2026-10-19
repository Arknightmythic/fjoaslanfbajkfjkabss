import os
import re
import json
from contextlib import contextmanager, asynccontextmanager
from typing import AsyncIterator, Optional, List, Dict, Any
from dotenv import load_dotenv
from loguru import logger
from pydantic import BaseModel, Field
from langchain.messages import SystemMessage, HumanMessage, AIMessage, AIMessageChunk
from langchain.agents import create_agent
from langchain.agents.middleware import TodoListMiddleware, ToolRetryMiddleware, SummarizationMiddleware
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from opik.integrations.langchain import OpikTracer

from src.prompts import SYNCHRONO_AGENT_SYSTEM_PROMPT, TITLE_GENERATOR_PROMPT
from src.tools import run_query, get_table_names, get_table_detail, load_skills
from src.middlewares import PromptInjectionGuardrail, PIIMiddleware
from src.databases.internal.config import INTERNAL_DB_URL, SessionLocal
from src.databases.internal.models import Conversation, Message
from src.semantic_cache import SemanticCache

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
            return OpenAIEmbeddings(
                model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
                api_key=os.getenv("OPENAI_API_KEY"),
                base_url=os.getenv("OPENAI_BASE_URL"),
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

    def generate_title(self, question: str) -> str:
        try:
            output: TitleOutput = self._chain.invoke({"question": question})
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
    ):
        self._model = ChatOpenAI(
            model=os.getenv("OPENAI_MODEL_NAME", "gemma4:31b-cloud"),
            base_url=os.getenv("OPENAI_BASE_URL"),
            api_key=os.getenv("OPENAI_API_KEY", "ollama"),
            temperature=0,
        )
        self._system_prompt = SystemMessage(SYNCHRONO_AGENT_SYSTEM_PROMPT)
        self._tools = [run_query, get_table_names, get_table_detail, load_skills]
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
        use_opik = os.getenv("USE_OPIK", "true").lower() in ("true", "1", "yes")
        self._callbacks = [OpikTracer()] if use_opik else []
        self._custom_checkpointer = checkpointer

        # Semantic cache with >90% confidence retrieval condition
        if semantic_cache is not None:
            self._semantic_cache = semantic_cache
        else:
            try:
                self._embedding = _get_default_embedding()
                self._semantic_cache = SemanticCache(
                    embedding=self._embedding,
                    max_distance=float(os.getenv("SEMANTIC_CACHE_DISTANCE", "0.10")),
                    min_confidence=float(os.getenv("SEMANTIC_CACHE_MIN_CONFIDENCE", "0.90")),
                )
            except Exception as e:
                logger.warning(f"Semantic cache could not be initialized: {e}")
                self._semantic_cache = None

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

    def invoke(self, thread_id: str, question: str, user_id: str = "default_user", enable_pii: bool = True) -> str:
        # 1. Check semantic cache (>90% confidence condition)
        if self._semantic_cache is not None:
            try:
                cached_answer = self._semantic_cache.get(question)
                if cached_answer is not None:
                    logger.info(f"[SemanticCache] Serving cached answer for invoke (>90% conf)")
                    return cached_answer
            except Exception as e:
                logger.error(f"[SemanticCache] Error checking cache in invoke: {e}")

        # 2. Run agent execution with PostgresSaver checkpointer
        _current_middleware = self._middleware.copy()
        if enable_pii:
            _current_middleware.extend([
                PIIMiddleware(pii_type="nik", detector=r"\b\d{16}\b", strategy="mask")
            ])

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
                "callbacks": self._callbacks
            }
            response = agent.invoke(
                {"messages": [HumanMessage(content=question)]},
                config=config
            )
            answer = response["messages"][-1].content

        # 3. Store response in semantic cache
        if self._semantic_cache is not None and answer:
            try:
                self._semantic_cache.set(question, answer)
            except Exception as e:
                logger.error(f"[SemanticCache] Error saving cache in invoke: {e}")

        return answer

    async def stream(self, user_id: str, conversation_id: str, question: str, enable_pii: bool = True):
        generated_title = None
        try:
            db = SessionLocal()
            conv = db.query(Conversation).filter_by(id=conversation_id).first()
            if not conv:
                generated_title = self.title_generator.generate_title(question)
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
        if self._semantic_cache is not None:
            try:
                cached_answer = self._semantic_cache.get(question)
            except Exception as e:
                logger.error(f"[SemanticCache] Error reading cache in stream: {e}")

        if cached_answer is not None:
            logger.info(f"[SemanticCache] Serving cached answer in stream (>90% conf)")
            yield f"data: {json.dumps({'step': 'START', 'content': ''})}\n\n"
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
            return

        # 2. Cache miss: execute agent with AsyncPostgresSaver checkpointer
        _current_middleware = self._middleware.copy()
        if enable_pii:
            _current_middleware.extend([
                PIIMiddleware(pii_type="nik", detector=r"\b\d{16}\b", strategy="mask")
            ])

        async with self._get_async_checkpointer() as checkpointer:
            _agent = create_agent(
                model=self._model,
                system_prompt=self._system_prompt,
                tools=self._tools,
                middleware=_current_middleware,
                checkpointer=checkpointer
            )
            start_payload = {
                "step": "START",              
                "content": "",           
            }
            yield f"data: {json.dumps(start_payload)}\n\n"

            final_response = ""
            async for chunk, metadata in _agent.astream(
                    {"messages": [HumanMessage(question)]},
                    stream_mode="messages",
                    config={
                        "configurable": {"thread_id": conversation_id}
                    }
                ):
                if metadata.get("ls_integration") == "langchain_chat_model" and (
                    metadata.get("langgraph_node") == "PromptInjectionGuardrail.before_agent"
                    or metadata.get("langgraph_node") == "SummarizationMiddleware.before_model"
                ):
                    continue

                data = {
                    "step": chunk.__class__.__name__,
                    "content": chunk.text,
                }

                if isinstance(chunk, AIMessageChunk) and chunk.tool_calls:
                    data["tool_calls"] = chunk.tool_calls

                if isinstance(chunk, AIMessageChunk) and not chunk.tool_calls:
                    final_response += chunk.text
                    
                yield f"data: {json.dumps(data)}\n\n"

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

            # 3. Store response in semantic cache
            if self._semantic_cache is not None and final_response:
                try:
                    self._semantic_cache.set(question, final_response)
                except Exception as e:
                    logger.error(f"[SemanticCache] Error caching response in stream: {e}")
