from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from src.handler import ChatbotHandler
from src.llm import GatewayChatOpenAI


def test_text_parts_are_sent_as_one_string():
    model = GatewayChatOpenAI(model="gemma4:31b", api_key="sk-test", base_url="http://gateway/v1")
    payload = model._get_request_payload([
        SystemMessage(content=[{"type": "text", "text": "Prompt"}, {"type": "text", "text": "Todo"}]),
        HumanMessage(content="Berapa job grading?"),
    ])

    assert payload["messages"][0]["content"] == "Prompt\n\nTodo"
    assert payload["messages"][1]["content"] == "Berapa job grading?"


def test_non_text_parts_are_left_as_they_are():
    model = GatewayChatOpenAI(model="gemma4:31b", api_key="sk-test", base_url="http://gateway/v1")
    parts = [{"type": "text", "text": "Apa ini?"},
             {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]
    payload = model._get_request_payload([HumanMessage(content=parts)])

    assert isinstance(payload["messages"][0]["content"], list)


class _FakeSaver:
    async def setup(self):
        return None


def _saver_factory(fail_on_open: bool):
    @asynccontextmanager
    async def from_conn_string(_uri):
        if fail_on_open:
            raise ConnectionError("postgres down")
        yield _FakeSaver()
    return from_conn_string


async def test_error_inside_the_block_is_not_hidden_by_the_checkpointer():
    owner = SimpleNamespace(_custom_checkpointer=None)
    with patch("src.handler.AsyncPostgresSaver.from_conn_string", _saver_factory(False)):
        with pytest.raises(ValueError, match="model 400"):
            async with ChatbotHandler._get_async_checkpointer(owner) as saver:
                assert isinstance(saver, _FakeSaver)
                raise ValueError("model 400")


async def test_unreachable_postgres_falls_back_to_memory_saver():
    from langgraph.checkpoint.memory import MemorySaver

    owner = SimpleNamespace(_custom_checkpointer=None)
    with patch("src.handler.AsyncPostgresSaver.from_conn_string", _saver_factory(True)):
        async with ChatbotHandler._get_async_checkpointer(owner) as saver:
            assert isinstance(saver, MemorySaver)
