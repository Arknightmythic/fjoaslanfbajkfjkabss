"""Opik-style local tracing: append-only JSONL plus nested per-trace JSON.

The JSONL file remains the audit stream. When a chat request completes, a
nested JSON document (input/output, spans grouped by parent, tool calls and
LLM calls) is written to ``CHATBOT_TRACE_JSON_DIR`` for easy inspection, which
is the local equivalent of an Opik trace page.

Question/answer text, LLM prompts/completions, and tool inputs/outputs are
stored when ``CHATBOT_TRACE_INCLUDE_CONTENT`` is enabled (default true),
truncated to ``CHATBOT_TRACE_PAYLOAD_MAX_CHARS`` and with 16-digit NIK values
masked as ``[NIK]``.
"""

from contextvars import ContextVar
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from threading import RLock
from typing import Any
from uuid import uuid4

from langchain_core.callbacks import BaseCallbackHandler
from loguru import logger

_bound_tracer: ContextVar["LocalFileTracer | None"] = ContextVar("local_trace", default=None)


def current_tracer() -> "LocalFileTracer | None":
    return _bound_tracer.get()


class LocalFileTracer(BaseCallbackHandler):
    """Write flat lifecycle events and a nested per-trace JSON document."""

    _FINAL_EVENTS = {"chat.request_completed", "chat.request_rejected"}
    _SPAN_PREFIXES = {"llm", "tool", "chain"}

    def __init__(
        self,
        trace_id: str | None = None,
        log_path: str | None = None,
        include_content: bool | None = None,
        json_dir: str | None = None,
        write_json: bool | None = None,
    ):
        self.trace_id = trace_id or str(uuid4())
        self.log_path = Path(log_path or os.getenv("CHATBOT_TRACE_FILE", "/app/data/logs/chatbot-traces.jsonl"))
        self.max_bytes = int(os.getenv("CHATBOT_TRACE_MAX_BYTES", str(10 * 1024 * 1024)))
        self.backup_count = max(1, int(os.getenv("CHATBOT_TRACE_BACKUP_COUNT", "5")))
        if include_content is None:
            include_content = os.getenv("CHATBOT_TRACE_INCLUDE_CONTENT", "true").strip().lower() not in {
                "0",
                "false",
                "no",
                "off",
            }
        self.include_content = include_content
        self.payload_max_chars = int(os.getenv("CHATBOT_TRACE_PAYLOAD_MAX_CHARS", "4000"))
        if write_json is None:
            write_json = os.getenv("CHATBOT_TRACE_WRITE_JSON", "true").strip().lower() not in {
                "0",
                "false",
                "no",
                "off",
            }
        self.write_json = write_json
        if json_dir is not None:
            self.json_dir = Path(json_dir)
        elif log_path is not None:
            self.json_dir = self.log_path.parent / "traces"
        else:
            self.json_dir = Path(os.getenv("CHATBOT_TRACE_JSON_DIR", str(self.log_path.parent / "traces")))
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._started_at: dict[str, datetime] = {}
        self._spans: dict[str, dict[str, Any]] = {}
        self._events: list[dict[str, Any]] = []
        self._trace_name = "trace"
        self._trace_start_time: str | None = None
        self._trace_end_time: str | None = None
        self._trace_input: dict[str, Any] = {}
        self._trace_output: dict[str, Any] = {}
        self._trace_metadata: dict[str, Any] = {}
        self._flushed = False

    @staticmethod
    def _safe(value: Any, limit: int = 160) -> str:
        text = str(value or "")
        text = re.sub(r"(?<!\d)\d{16}(?!\d)", "[NIK]", text)
        return re.sub(r"[\r\n\t]+", " ", text)[:limit]

    @staticmethod
    def _stringify(value: Any) -> str:
        if isinstance(value, str):
            return value
        content = getattr(value, "content", None)
        if isinstance(content, str):
            return content
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            return str(value or "")

    @classmethod
    def _messages_text(cls, messages: Any) -> str:
        batch = messages[0] if isinstance(messages, list) and messages and isinstance(messages[0], list) else messages
        if not isinstance(batch, list):
            return cls._stringify(batch)
        rendered = []
        for message in batch:
            if isinstance(message, dict):
                role = message.get("role") or message.get("type") or "unknown"
                content = message.get("content")
            else:
                role = getattr(message, "type", None) or message.__class__.__name__
                content = getattr(message, "content", None)
            rendered.append(f"{role}: {cls._stringify(content)}")
        return "\n".join(rendered)

    def _payload(self, value: Any) -> str:
        text = re.sub(r"(?<!\d)\d{16}(?!\d)", "[NIK]", self._stringify(value)).strip()
        if len(text) > self.payload_max_chars:
            text = f"{text[: self.payload_max_chars]}…[truncated]"
        return text

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        if not self.log_path.exists() or self.log_path.stat().st_size + incoming_bytes <= self.max_bytes:
            return
        oldest = self.log_path.with_name(f"{self.log_path.name}.{self.backup_count}")
        oldest.unlink(missing_ok=True)
        for index in range(self.backup_count - 1, 0, -1):
            source = self.log_path.with_name(f"{self.log_path.name}.{index}")
            if source.exists():
                source.replace(self.log_path.with_name(f"{self.log_path.name}.{index + 1}"))
        self.log_path.replace(self.log_path.with_name(f"{self.log_path.name}.1"))

    _PAYLOAD_KEYS = {"question", "answer", "input", "output"}

    @staticmethod
    def _duration_between(start: str | None, end: str | None) -> float | None:
        if not start or not end:
            return None
        try:
            delta = datetime.fromisoformat(end) - datetime.fromisoformat(start)
            return round(delta.total_seconds() * 1000, 2)
        except Exception:
            return None

    def _observe_trace_event(self, record: dict[str, Any]) -> None:
        event = record["event"]
        self._events.append(record)
        if self._trace_start_time is None:
            self._trace_start_time = record["timestamp"]
        if event.startswith("chat."):
            self._trace_name = "chat"
        elif event.startswith("document."):
            self._trace_name = "document-ingest"
        for key in ("route", "thread_id", "pii_enabled"):
            if key in record:
                self._trace_metadata[key] = record[key]
        if record.get("question"):
            self._trace_input = {"question": record["question"]}
        if event in self._FINAL_EVENTS:
            self._trace_end_time = record["timestamp"]
            if record.get("answer") is not None:
                self._trace_output = {"answer": record["answer"]}
            self._flush_trace()

    def _flush_trace(self) -> None:
        if not self.write_json or self._flushed:
            return
        self._flushed = True
        try:
            span_map = {span_id: span for span_id, span in self._spans.items()}
            for span in span_map.values():
                span["children"] = []
            roots: list[dict[str, Any]] = []
            for span in span_map.values():
                parent = span_map.get(str(span.get("parent_id") or ""))
                if parent is not None and parent is not span:
                    parent["children"].append(span)
                else:
                    roots.append(span)

            def sort_spans(items: list[dict[str, Any]]) -> None:
                items.sort(key=lambda item: item.get("start_time") or "")
                for item in items:
                    sort_spans(item["children"])

            sort_spans(roots)
            start_time = self._trace_start_time
            end_time = self._trace_end_time or start_time
            events = [
                {key: value for key, value in event.items() if key != "trace_id"}
                for event in self._events
                if event["event"].split(".", 1)[0] not in self._SPAN_PREFIXES
                and event["event"] not in self._FINAL_EVENTS
                and event["event"] != "chat.request_started"
            ]
            payload = {
                "trace_id": self.trace_id,
                "name": self._trace_name,
                "start_time": start_time,
                "end_time": end_time,
                "duration_ms": self._duration_between(start_time, end_time),
                "input": self._trace_input,
                "output": self._trace_output,
                "metadata": self._trace_metadata,
                "spans": roots,
                "events": events,
            }
            safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", self.trace_id)
            self.json_dir.mkdir(parents=True, exist_ok=True)
            target = self.json_dir / f"{safe_id}.json"
            temporary = self.json_dir / f".{safe_id}.{os.getpid()}.tmp"
            temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            temporary.replace(target)
        except Exception as exc:
            logger.warning(f"[LocalFileTracer] Could not write trace JSON for {self.trace_id}: {exc}")

    def log_event(self, event: str, **fields: Any) -> None:
        safe_fields = {}
        for key, value in fields.items():
            if value is None:
                continue
            if isinstance(value, str):
                if key in self._PAYLOAD_KEYS:
                    if not self.include_content:
                        continue
                    safe_fields[key] = self._payload(value)
                else:
                    safe_fields[key] = self._safe(value)
            elif isinstance(value, (int, float, bool)):
                safe_fields[key] = value
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trace_id": self.trace_id,
            "event": event,
            **safe_fields,
        }
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        encoded = line.encode("utf-8")
        with self._lock:
            self._rotate_if_needed(len(encoded))
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(line)
            self._observe_trace_event(record)

    def bind(self):
        """Context manager binding this tracer for nested guardrail callbacks."""
        return _TraceBinding(self)

    def _start(
        self,
        kind: str,
        run_id: Any,
        name: Any = None,
        model: Any = None,
        payload: Any = None,
        parent_id: Any = None,
    ) -> None:
        started = datetime.now(timezone.utc)
        span_id = str(run_id)
        self._started_at[span_id] = started
        span = {
            "id": span_id,
            "parent_id": None if parent_id is None else str(parent_id),
            "type": kind,
            "name": str(name or model or kind),
            "start_time": started.isoformat(),
            "end_time": None,
            "duration_ms": None,
            "status": "running",
        }
        if model:
            span["model"] = self._safe(model)
        if self.include_content and payload is not None:
            span["input"] = self._payload(payload)
        with self._lock:
            self._spans[span_id] = span
        fields = {"run_kind": kind}
        if name:
            fields["name"] = self._safe(name)
        if model:
            fields["model"] = self._safe(model)
        if self.include_content and payload is not None:
            fields["input"] = self._payload(payload)
        self.log_event(f"{kind}.started", run_id=self._safe(run_id, 64), **fields)

    def _finish(self, kind: str, run_id: Any, error: BaseException | None = None, payload: Any = None) -> None:
        started = self._started_at.pop(str(run_id), None)
        finished = datetime.now(timezone.utc)
        duration = None if started is None else round((finished - started).total_seconds() * 1000, 2)
        span = self._spans.get(str(run_id))
        if span is not None:
            span["end_time"] = finished.isoformat()
            span["duration_ms"] = duration
            span["status"] = "failed" if error is not None else "completed"
            if error is not None:
                span["error_type"] = type(error).__name__
            if self.include_content and payload is not None:
                span["output"] = self._payload(payload)
        fields = {"run_kind": kind, "duration_ms": duration}
        if error is not None:
            fields["error_type"] = type(error).__name__
        if self.include_content and payload is not None:
            fields["output"] = self._payload(payload)
        self.log_event(f"{kind}.{'failed' if error else 'completed'}", run_id=self._safe(run_id, 64), **fields)

    @staticmethod
    def _serialized_name(serialized: dict[str, Any], metadata: Any = None) -> str | None:
        name = serialized.get("name")
        if name:
            return str(name)
        if isinstance(metadata, dict) and metadata.get("langgraph_node"):
            return str(metadata["langgraph_node"])
        identifier = serialized.get("id")
        if isinstance(identifier, (list, tuple)) and identifier:
            return str(identifier[-1])
        if identifier:
            return str(identifier)
        return None

    @staticmethod
    def _llm_output(response: Any) -> Any:
        generations = getattr(response, "generations", None) or []
        if generations and generations[0]:
            generation = generations[0][0]
            text = getattr(generation, "text", None)
            if text:
                return text
            message = getattr(generation, "message", None)
            if message is not None:
                return getattr(message, "content", message)
        return response

    def on_llm_start(self, serialized: dict[str, Any], prompts: list[str], *, run_id: Any, **kwargs: Any) -> None:
        serialized = serialized or {}
        invocation = kwargs.get("invocation_params") or {}
        self._start(
            "llm",
            run_id,
            model=invocation.get("model") or invocation.get("model_name") or serialized.get("name"),
            payload="\n".join(prompts),
            parent_id=kwargs.get("parent_run_id"),
        )

    def on_chat_model_start(self, serialized: dict[str, Any], messages: list[list[Any]], *, run_id: Any, **kwargs: Any) -> None:
        serialized = serialized or {}
        invocation = kwargs.get("invocation_params") or {}
        self._start(
            "llm",
            run_id,
            model=invocation.get("model") or invocation.get("model_name") or serialized.get("name"),
            payload=self._messages_text(messages),
            parent_id=kwargs.get("parent_run_id"),
        )

    def on_llm_end(self, response: Any, *, run_id: Any, **kwargs: Any) -> None:
        self._finish("llm", run_id, payload=self._llm_output(response))

    def on_llm_error(self, error: BaseException, *, run_id: Any, **kwargs: Any) -> None:
        self._finish("llm", run_id, error)

    def on_tool_start(self, serialized: dict[str, Any], input_str: str, *, run_id: Any, **kwargs: Any) -> None:
        serialized = serialized or {}
        self._start(
            "tool",
            run_id,
            name=self._serialized_name(serialized, kwargs.get("metadata")),
            payload=input_str,
            parent_id=kwargs.get("parent_run_id"),
        )

    def on_tool_end(self, output: Any, *, run_id: Any, **kwargs: Any) -> None:
        self._finish("tool", run_id, payload=output)

    def on_tool_error(self, error: BaseException, *, run_id: Any, **kwargs: Any) -> None:
        self._finish("tool", run_id, error)

    def on_chain_start(self, serialized: dict[str, Any], inputs: dict[str, Any], *, run_id: Any, **kwargs: Any) -> None:
        serialized = serialized or {}
        self._start(
            "chain",
            run_id,
            name=self._serialized_name(serialized, kwargs.get("metadata")),
            parent_id=kwargs.get("parent_run_id"),
        )

    def on_chain_end(self, outputs: dict[str, Any], *, run_id: Any, **kwargs: Any) -> None:
        self._finish("chain", run_id)

    def on_chain_error(self, error: BaseException, *, run_id: Any, **kwargs: Any) -> None:
        self._finish("chain", run_id, error)


class _TraceBinding:
    def __init__(self, tracer: LocalFileTracer):
        self.tracer = tracer
        self.token = None

    def __enter__(self):
        self.token = _bound_tracer.set(self.tracer)
        return self.tracer

    def __exit__(self, exc_type, exc, tb):
        if self.token is not None:
            _bound_tracer.reset(self.token)
