import re
from hashlib import sha256
from typing import Literal
from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain.messages import HumanMessage
from langgraph.runtime import Runtime

class PIIMiddleware(AgentMiddleware):
    """
    Double Protection PII Guardrail:
    1. before_agent: Sanitizes user input (e.g. 16-digit NIK) before reaching LLM & Guardrails.
    2. after_agent: Sanitizes outgoing model output before returning to frontend.
    """
    def __init__(self, pii_type: str = "nik", detector: str = r"\b\d{16}\b", strategy: Literal["mask", "redact", "hash"] = "mask"):
        self._pii_type = pii_type
        self._detector = detector
        self._strategy = strategy

    @property
    def name(self) -> str:
        return f"{self.__class__.__name__}[{self._pii_type}]"

    def _sanitize(self, text: str) -> str:
        if not text:
            return text
        matches = re.findall(self._detector, text)
        for match in matches:
            if self._strategy == "mask":
                # Mask all digits except the last 3 (e.g. *************123)
                masked = f"{'*' * (len(match) - 3)}{match[-3:]}"
                text = text.replace(match, masked)
            elif self._strategy == "redact":
                text = text.replace(match, "[REDACTED_NIK]")
            elif self._strategy == "hash":
                hashed = sha256(match.encode()).hexdigest()[:8]
                text = text.replace(match, f"[HASH:{hashed}]")
        return text

    def before_agent(self, state: AgentState, runtime: Runtime) -> AgentState:
        """Incoming protection: mask sensitive NIK in user prompt before processing."""
        messages = state.get("messages")
        if not messages:
            return state

        last_msg = messages[-1]
        if isinstance(last_msg, HumanMessage) and hasattr(last_msg, "content") and last_msg.content:
            text = last_msg.content if isinstance(last_msg.content, str) else str(last_msg.content)
            sanitized = self._sanitize(text)
            if sanitized != text:
                last_msg.content = sanitized
        return state

    def after_agent(self, state: AgentState, runtime: Runtime) -> AgentState:
        """Outgoing protection: mask any sensitive NIK in generated response."""
        messages = state.get("messages")
        if not messages:
            return state

        last_msg = messages[-1]
        if hasattr(last_msg, "content") and last_msg.content:
            text = last_msg.content if isinstance(last_msg.content, str) else str(last_msg.content)
            last_msg.content = self._sanitize(text)
        return state
