import json
from types import SimpleNamespace

from src.observability.file_tracer import LocalFileTracer


def _records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _flatten_spans(spans):
    for span in spans:
        yield span
        yield from _flatten_spans(span.get("children", []))


def test_local_tracer_writes_lifecycle_metadata_without_payloads_when_disabled(tmp_path):
    path = tmp_path / "traces.jsonl"
    tracer = LocalFileTracer(trace_id="trace-test", log_path=str(path), include_content=False)

    tracer.log_event("chat.request_started", route="faq", prompt="NIK 3171012345678901")
    tracer.on_chat_model_start(
        {"name": "ChatOpenAI"},
        [[{"role": "user", "content": "raw private prompt"}]],
        run_id="llm-run-1",
        invocation_params={"model": "gemma4:31b-cloud"},
    )
    tracer.on_llm_end(object(), run_id="llm-run-1")
    tracer.on_tool_start({"name": "run_query"}, "SELECT private data", run_id="tool-run-1")
    tracer.on_tool_end("private query output", run_id="tool-run-1")

    records = _records(path)
    assert [record["event"] for record in records] == [
        "chat.request_started",
        "llm.started",
        "llm.completed",
        "tool.started",
        "tool.completed",
    ]
    content = path.read_text(encoding="utf-8")
    assert "3171012345678901" not in content
    assert "raw private prompt" not in content
    assert "SELECT private data" not in content
    assert "private query output" not in content
    assert "[NIK]" in content


def test_local_tracer_includes_question_answer_prompts_and_tool_payloads(tmp_path):
    path = tmp_path / "traces.jsonl"
    tracer = LocalFileTracer(trace_id="trace-content", log_path=str(path), include_content=True)

    tracer.log_event("chat.request_started", route="agent", question="Apa isi SOP NIK 3171012345678901?")
    tracer.on_chat_model_start(
        {"name": "ChatOpenAI"},
        [[{"role": "user", "content": "Siapa peserta batch fav-001?"}]],
        run_id="llm-run-1",
        invocation_params={"model": "gemma4:31b-cloud"},
    )
    tracer.on_llm_end(
        SimpleNamespace(generations=[[SimpleNamespace(text="Jawaban akhir LLM")]]),
        run_id="llm-run-1",
    )
    tracer.on_tool_start({"name": "run_query"}, "SELECT COUNT(*) FROM uploaded_files", run_id="tool-run-1")
    tracer.on_tool_end("total_batches\tunique_files\n20\t7", run_id="tool-run-1")
    tracer.log_event("chat.request_completed", route="agent", answer="Terdapat 20 batch.")

    records = _records(path)
    assert records[0]["question"] == "Apa isi SOP NIK [NIK]?"
    assert records[1]["input"] == "user: Siapa peserta batch fav-001?"
    assert records[1]["model"] == "gemma4:31b-cloud"
    assert records[2]["output"] == "Jawaban akhir LLM"
    assert records[3]["name"] == "run_query"
    assert records[3]["input"] == "SELECT COUNT(*) FROM uploaded_files"
    assert records[4]["output"] == "total_batches\tunique_files\n20\t7"
    assert records[5]["answer"] == "Terdapat 20 batch."
    assert "3171012345678901" not in path.read_text(encoding="utf-8")


def test_local_tracer_writes_nested_trace_json_on_chat_completion(tmp_path):
    path = tmp_path / "traces.jsonl"
    tracer = LocalFileTracer(trace_id="trace-json", log_path=str(path), include_content=True)

    tracer.log_event(
        "chat.request_started",
        route="agent",
        thread_id="thread-1",
        pii_enabled=True,
        question="Berapa batch NIK 3171012345678901?",
    )
    tracer.log_event("guardrail.checked", allowed=True)
    tracer.on_chain_start({"name": "AgentExecutor"}, {}, run_id="chain-1")
    tracer.on_tool_start(
        {"name": "run_query"},
        "SELECT COUNT(*) FROM uploaded_files",
        run_id="tool-1",
        parent_run_id="chain-1",
    )
    tracer.on_tool_end("20", run_id="tool-1")
    tracer.on_chain_end({}, run_id="chain-1")
    tracer.on_chain_start(None, {}, run_id="chain-null")
    tracer.on_chain_end({}, run_id="chain-null")
    tracer.on_chat_model_start(
        {"name": "ChatOpenAI"},
        [[{"role": "user", "content": "Jawab singkat"}]],
        run_id="llm-1",
        invocation_params={"model": "gemma4:31b-cloud"},
    )
    tracer.on_llm_end(
        SimpleNamespace(generations=[[SimpleNamespace(text="Ada 20 batch.")]]),
        run_id="llm-1",
    )
    tracer.log_event("chat.request_completed", route="agent", answer="Ada 20 batch.")

    trace = json.loads((tmp_path / "traces" / "trace-json.json").read_text(encoding="utf-8"))
    assert trace["trace_id"] == "trace-json"
    assert trace["name"] == "chat"
    assert trace["input"] == {"question": "Berapa batch NIK [NIK]?"}
    assert trace["output"] == {"answer": "Ada 20 batch."}
    assert trace["metadata"] == {"route": "agent", "thread_id": "thread-1", "pii_enabled": True}
    assert trace["duration_ms"] >= 0

    spans = list(_flatten_spans(trace["spans"]))
    chain = next(span for span in spans if span["id"] == "chain-1")
    null_chain = next(span for span in spans if span["id"] == "chain-null")
    tool = next(span for span in spans if span["id"] == "tool-1")
    llm = next(span for span in spans if span["id"] == "llm-1")
    assert null_chain["name"] == "chain"
    assert chain["children"] == [tool]
    assert tool["parent_id"] == "chain-1"
    assert tool["input"] == "SELECT COUNT(*) FROM uploaded_files"
    assert tool["output"] == "20"
    assert tool["status"] == "completed"
    assert llm["model"] == "gemma4:31b-cloud"
    assert llm["output"] == "Ada 20 batch."
    assert [event["event"] for event in trace["events"]] == ["guardrail.checked"]
    assert trace["events"][0]["allowed"] is True


def test_local_tracer_can_disable_per_trace_json(tmp_path):
    path = tmp_path / "traces.jsonl"
    tracer = LocalFileTracer(trace_id="trace-no-json", log_path=str(path), write_json=False)

    tracer.log_event("chat.request_started", route="faq", question="Apa itu Synchrono?")
    tracer.log_event("chat.request_completed", route="faq", answer="Platform Synchrono.")

    assert not (tmp_path / "traces" / "trace-no-json.json").exists()


def test_local_tracer_truncates_long_payloads(tmp_path):
    path = tmp_path / "traces.jsonl"
    tracer = LocalFileTracer(trace_id="trace-truncate", log_path=str(path), include_content=True)
    tracer.payload_max_chars = 25

    tracer.on_tool_start({"name": "run_query"}, "x" * 100, run_id="tool-run-2")

    record = _records(path)[0]
    assert record["input"].endswith("…[truncated]")
    assert len(record["input"]) == 25 + len("…[truncated]")


def test_local_tracer_rotates_file_by_size(tmp_path):
    path = tmp_path / "traces.jsonl"
    tracer = LocalFileTracer(trace_id="trace-rotate", log_path=str(path))
    tracer.max_bytes = 150
    tracer.backup_count = 2

    for index in range(8):
        tracer.log_event("test.event", sequence=index, marker="x" * 80)

    assert path.exists()
    assert path.with_name("traces.jsonl.1").exists()
