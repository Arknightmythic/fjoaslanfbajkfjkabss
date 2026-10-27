"""Chat model for OpenAI-compatible gateways."""
from typing import Any

from langchain_openai import ChatOpenAI


def _flatten_text_parts(content: Any) -> Any:
    """[{"type": "text", "text": ...}, ...] -> one string; any other content as it is."""
    if isinstance(content, list) and content and all(
        isinstance(part, dict) and part.get("type") == "text" for part in content
    ):
        return "\n\n".join(part.get("text", "") for part in content)
    return content


class GatewayChatOpenAI(ChatOpenAI):
    """ChatOpenAI that sends text-only message content as a plain string.

    LangChain agents build some messages (the system prompt with the middleware
    additions) as a list of text parts. That is valid OpenAI input, but stricter
    OpenAI-compatible gateways such as ollama-proxies accept only a string or null
    and answer 400 "messages.0.content: Invalid input".
    """

    def _get_request_payload(self, input_: Any, *, stop: list[str] | None = None,
                             **kwargs: Any) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        for message in payload.get("messages", []):
            if "content" in message:
                message["content"] = _flatten_text_parts(message["content"])
        return payload
