import os
import re
from typing import Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain.agents.middleware import AgentMiddleware, AgentState, hook_config
from langchain.messages import AIMessageChunk, HumanMessage
from langchain.chat_models import init_chat_model
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime
from chatbot.prompts import PROMPT_INJECTION_GUARDRAIL_PROMPT

load_dotenv()

class PromptInjectionGuardrailOutput(BaseModel):
    is_dangerous: bool = Field(..., description="security status of the user query")
    answer: Optional[str] = Field(
        default="", 
        description="safe refusal response in Indonesian if dangerous, otherwise empty."
    )

class PromptInjectionGuardrail(AgentMiddleware):
    def __init__(self, model_name: Optional[str] = None, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.model_name = model_name or os.getenv("OPENAI_MODEL_NAME") or os.getenv("GUARDRAIL_MODEL", "gemma4:31b-cloud")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL") or os.getenv("OLLAMA_BASE_URL")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("OLLAMA_API_KEY") or "ollama"
        
        self._prompt = PromptTemplate.from_template(PROMPT_INJECTION_GUARDRAIL_PROMPT)
        self._llm = None
        try:
            kwargs = {"temperature": 0, "api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            base_llm = init_chat_model(
                self.model_name,
                model_provider="openai",
                **kwargs
            )
            self._llm = base_llm.with_structured_output(PromptInjectionGuardrailOutput)
            self._chain = self._prompt | self._llm
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

        # 1. Fast Heuristic Rule Check for Obvious Malicious Attacks
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
                return {
                    "jump_to": "end",
                    "messages": [AIMessageChunk("Maaf, permintaan ini tidak dapat diproses karena alasan keamanan sistem.")]
                }

        # 2. LLM-based Evaluation (if chain is active)
        if self._chain:
            try:
                result: PromptInjectionGuardrailOutput = self._chain.invoke({"user_query": text})
                if isinstance(result, PromptInjectionGuardrailOutput) and result.is_dangerous:
                    refusal = result.answer or "Maaf, permintaan ini melanggar kebijakan keamanan sistem."
                    return {"jump_to": "end", "messages": [AIMessageChunk(refusal)]}
            except Exception as e:
                try:
                    match = re.search(r"\{.*?\}", str(e), re.DOTALL)
                    if match:
                        import json
                        data = json.loads(match.group(0))
                        if data.get("is_dangerous"):
                            refusal = data.get("answer") or "Maaf, permintaan ini melanggar kebijakan keamanan sistem."
                            return {"jump_to": "end", "messages": [AIMessageChunk(refusal)]}
                        return {"jump_to": "model"}
                except Exception:
                    pass
                print(f"[Guardrail Notice] LLM evaluation skipped/timed out: {e}")

        return {"jump_to": "model"}
