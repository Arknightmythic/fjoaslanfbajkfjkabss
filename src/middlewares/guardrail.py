import os
import re
from typing import Optional
from dotenv import load_dotenv
from loguru import logger
from pydantic import BaseModel, Field
from langchain.agents.middleware import AgentMiddleware, AgentState, hook_config
from langchain.messages import AIMessageChunk, HumanMessage
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
# Under the ChatOpenAI name, so the tests that patch guardrail.ChatOpenAI keep working.
from src.llm import GatewayChatOpenAI as ChatOpenAI
from langgraph.runtime import Runtime
from src.prompts import PROMPT_INJECTION_GUARDRAIL_PROMPT
from src.observability.file_tracer import current_tracer

load_dotenv()

class PromptInjectionGuardrailOutput(BaseModel):
    is_dangerous: bool = Field(..., description="security status of the user query")
    answer: Optional[str] = Field(
        default="", 
        description="safe refusal response in Indonesian if dangerous, otherwise empty."
    )

class PromptInjectionGuardrail(AgentMiddleware):
    def __init__(self):
        self.model_name = os.getenv("OPENAI_MODEL_NAME", "gemma4:31b-cloud")
        self.base_url = os.getenv("OPENAI_BASE_URL")
        self.api_key = os.getenv("OPENAI_API_KEY", "ollama")
        
        self._parser = PydanticOutputParser(pydantic_object=PromptInjectionGuardrailOutput)
        self._prompt = PromptTemplate.from_template(
            PROMPT_INJECTION_GUARDRAIL_PROMPT,
            partial_variables={"format_instructions": self._parser.get_format_instructions()},
        )
        self._model = None
        self._chain = None
        try:
            self._model = ChatOpenAI(
                model=self.model_name,
                base_url=self.base_url,
                api_key=self.api_key,
                temperature=0,
            )
            self._chain = self._prompt | self._model | self._parser
        except Exception:
            self._chain = None

    @hook_config(can_jump_to=["end", "model"])
    def before_agent(self, state: AgentState, runtime: Runtime) -> AgentState:
        messages = state.get("messages")
        if not messages:
            return {"jump_to": "model"}
        
        last_message = messages[-1]
        if not isinstance(last_message, HumanMessage) or not last_message.content:
            return {"jump_to": "model"}

        text = last_message.content if isinstance(last_message.content, str) else str(last_message.content)
        tracer = current_tracer()
        if tracer:
            tracer.log_event("guardrail.check_started")

        malicious_patterns = [
            r"ignore\s+(all\s+)?(previous\s+)?instructions",
            r"tampilkan\s+system\s+prompt",
            r"act\s+as\s+DAN\b",
            r"drop\s+database\b",
            r"delete\s+from\s+users\b",
            r"truncate\s+table\b"
        ]
        for pat in malicious_patterns:
            if re.search(pat, text, re.IGNORECASE):
                if tracer:
                    tracer.log_event("guardrail.check_completed", decision="blocked", match_type="heuristic")
                return {
                    "jump_to": "end",
                    "messages": [AIMessageChunk("Maaf, permintaan ini tidak dapat diproses karena alasan keamanan sistem.")]
                }

        if self._chain:
            try:
                result: PromptInjectionGuardrailOutput = self._chain.invoke(
                    {"user_query": text},
                    config={"callbacks": [tracer] if tracer else []},
                )
                if result.is_dangerous:
                    if tracer:
                        tracer.log_event("guardrail.check_completed", decision="blocked")
                    refusal = result.answer or "Maaf, permintaan ini melanggar kebijakan keamanan sistem."
                    return {"jump_to": "end", "messages": [AIMessageChunk(refusal)]}
                if tracer:
                    tracer.log_event("guardrail.check_completed", decision="allowed")
            except Exception as e:
                try:
                    match = re.search(r"\{.*?\}", str(e), re.DOTALL)
                    if match:
                        import json
                        data = json.loads(match.group(0))
                        if data.get("is_dangerous"):
                            if tracer:
                                tracer.log_event("guardrail.check_completed", decision="blocked")
                            raw_answer = data.get("answer")
                            refusal = raw_answer if raw_answer else "Maaf, permintaan ini melanggar kebijakan keamanan sistem."
                            return {"jump_to": "end", "messages": [AIMessageChunk(refusal)]}
                        return {"jump_to": "model"}
                except Exception:
                    pass
                logger.warning("Guardrail Notice: LLM evaluation skipped/timed out: {}", e)
                if tracer:
                    tracer.log_event("guardrail.check_failed", error_type=type(e).__name__)

        elif tracer:
            tracer.log_event("guardrail.check_skipped", reason="guardrail_model_unavailable")
        return {"jump_to": "model"}
