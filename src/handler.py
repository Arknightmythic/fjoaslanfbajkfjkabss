import os
import re
import json
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

load_dotenv()


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
    def __init__(self):
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

    def invoke(self, thread_id: str, question: str, user_id: str = "default_user", enable_pii: bool = True) -> str:
        config = {
            "configurable": {"thread_id": thread_id},
            "callback": self._callbacks
        }

        with PostgresSaver().from_conn_string(INTERNAL_DB_URL) as checkpointer:
            checkpointer.setup()
            agent = create_agent(
                model=self._model,
                tools=self._tools,
                system_prompt=self._system_prompt,
                checkpointer=checkpointer,
                middleware=self._middlewares,
            )

            config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}
            response = agent.invoke(
                {"messages": [HumanMessage(content=question)]},
                config=config
            )
        return response["messages"][-1].content

    async def stream(self, user_id: str, conversation_id: str, question: str, enable_pii: bool = True):
        try:
            db = SessionLocal()
            conv = db.query(Conversation).filter_by(id=conversation_id).first()
            if not conv:
                title = self.title_generator.generate_title(question)
                conv = Conversation(
                    id=conversation_id, 
                    user_id=user_id, 
                    thread_id=conversation_id,
                    title=title
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
            db.close()

        _current_middleware = self._middleware.copy()
        if enable_pii:
            _current_middleware.extend([
                PIIMiddleware(pii_type="nik", detector=r"\b\d{16}\b", strategy="mask")
            ])

        _agent = create_agent(
                model=self._model,
                system_prompt=self._system_prompt,
                tools=self._tools,
                middleware=_current_middleware,
                checkpointer=self._memory
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
            if metadata["ls_integration"] == "langchain_chat_model" and (metadata["langgraph_node"] == "PromptInjectionGuardrail.before_agent" or metadata["langgraph_node"] == "SummarizationMiddleware.before_model"):
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
        
        if self._generator_result:
            title_payload = {
                "step": "TITLE",
                "content": self._generator_result.title
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
            db.close()
