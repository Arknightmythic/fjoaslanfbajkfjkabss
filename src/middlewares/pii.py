import re
from hashlib import sha256
from typing import Literal
from langchain.agents.middleware import AgentMiddleware, AgentState
from langgraph.runtime import Runtime


class PIIMiddleware(AgentMiddleware):
    """Mask PII in all conversation/tool messages immediately before model calls."""

    def __init__(
        self,
        pii_type: str = "nik",
        detector: str = r"(?<!\d)\d{16}(?!\d)",
        strategy: Literal["mask", "redact", "hash"] = "mask",
    ):
        super().__init__()
        self._pii_type = pii_type
        self._detector = re.compile(detector)
        self._strategy = strategy

    @property
    def name(self) -> str:
        return f"{self.__class__.__name__}[{self._pii_type}]"

    def sanitize_text(self, text: str) -> str:
        if not text:
            return text
        def replace(match: re.Match[str]) -> str:
            value = match.group(0)
            if self._strategy == "mask":
                # Mask all digits except the last 3 (e.g. *************123)
                return f"{'*' * (len(value) - 3)}{value[-3:]}"
            if self._strategy == "redact":
                return "[REDACTED_NIK]"
            hashed = sha256(value.encode("utf-8")).hexdigest()[:8]
            return f"[HASH:{hashed}]"

        return self._detector.sub(replace, text)

    def sanitize_content(self, content):
        """Sanitize strings in LangChain text/block content without altering other values."""
        if isinstance(content, str):
            return self.sanitize_text(content)
        if isinstance(content, list):
            sanitized = [self.sanitize_content(item) for item in content]
            return sanitized
        if isinstance(content, dict):
            return {key: self.sanitize_content(value) for key, value in content.items()}
        return content

    def before_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        """Mask PII in user messages and tool results before they reach the model."""
        messages = state.get("messages")
        if not messages:
            return None

        sanitized_messages = []
        changed = False
        for message in messages:
            content = getattr(message, "content", None)
            sanitized_content = self.sanitize_content(content)
            if sanitized_content != content:
                changed = True
                if hasattr(message, "model_copy"):
                    message = message.model_copy(update={"content": sanitized_content})
                else:
                    message.content = sanitized_content
            sanitized_messages.append(message)

        return {"messages": sanitized_messages} if changed else None


class PIIStreamSanitizer:
    """Hold a short output suffix so 16-digit values split across tokens are masked."""

    def __init__(self, pii_middleware: PIIMiddleware, holdback: int = 17):
        self._pii = pii_middleware
        self._holdback = holdback
        self._pending = ""

    def feed(self, text: str, *, final: bool = False) -> str:
        self._pending += text or ""
        # Sanitize before releasing any prefix; the holdback preserves a possible
        # number split over successive model tokens until the full number is known.
        self._pending = self._pii.sanitize_text(self._pending)
        if final:
            released, self._pending = self._pending, ""
            return released
        if len(self._pending) <= self._holdback:
            return ""
        release_at = len(self._pending) - self._holdback
        released, self._pending = self._pending[:release_at], self._pending[release_at:]
        return released
