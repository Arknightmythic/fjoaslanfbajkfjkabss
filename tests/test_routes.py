import pytest
from fastapi.testclient import TestClient
from main import app
from chatbot.database import conv_db

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "synchrono-chatbot"
    assert "version" in data
    assert "postgres_db" in data
    assert "analytics_db" in data

def test_conversations_flow():
    test_user = "test_user_pytest"
    test_conv_id = "test-conv-001"
    
    # 1. Create conversation record
    conv_db.insert_conversation(
        conversation_id=test_conv_id,
        title="Uji Otomatis Percakapan",
        user_id=test_user
    )
    conv_db.insert_message(
        conversation_id=test_conv_id,
        content="Halo ini tes pertanyaan",
        role="human"
    )

    # 2. Get list of conversations
    res = client.get(f"/api/v1/conversations?user_id={test_user}")
    assert res.status_code == 200
    convs = res.json()
    assert len(convs) >= 1
    assert any(c["id"] == test_conv_id for c in convs)

    # 3. Get messages for the conversation
    res_msg = client.get(f"/api/v1/conversations/{test_conv_id}")
    assert res_msg.status_code == 200
    msgs = res_msg.json()
    assert len(msgs) >= 1
    assert msgs[0]["role"] == "human"

    # 4. Delete conversation
    del_res = client.delete(f"/api/v1/conversations/{test_conv_id}")
    assert del_res.status_code == 200

    # 5. Verify deleted
    res_after = client.get(f"/api/v1/conversations/{test_conv_id}")
    assert res_after.status_code == 200
    assert len(res_after.json()) == 0

def test_query_safety_validation():
    from chatbot.tools.db_query_executor import run_query

    # Dangerous query should be rejected
    dangerous_res = run_query.invoke({"query": "DROP TABLE uploaded_files;"})
    assert dangerous_res.get("is_dangerous") is True

    # Safe SELECT should be permitted
    safe_res = run_query.invoke({"query": "SELECT COUNT(*) FROM ref_grades;"})
    assert safe_res.get("is_dangerous") is False
    assert "query_result" in safe_res

def test_investigate_endpoint():
    res = client.get("/api/v1/investigate/fav-001")
    assert res.status_code == 200
    data = res.json()
    assert "file" in data
    assert "manual_matches" in data
    assert data["file"]["file_id"] == "fav-001"
    assert data["file"]["grade"] in ("D", 4)
    assert isinstance(data["manual_matches"], list)

def test_get_chatbot_handler_caching():
    from unittest.mock import patch
    import api.routes as r_mod
    r_mod._DEFAULT_HANDLER = None
    with patch("api.routes.ChatbotHandler") as mock_cls:
        mock_instance = object()
        mock_cls.return_value = mock_instance
        h1 = r_mod.get_chatbot_handler()
        h2 = r_mod.get_chatbot_handler()
        assert h1 is h2
        assert mock_cls.call_count == 1
    r_mod._DEFAULT_HANDLER = None

def test_database_schema_context_tool():
    from chatbot.tools.schema_context import get_schemas, get_allowed_schema_config
    
    # Test allowed schema config from .env
    config = get_allowed_schema_config()
    assert "uploaded_files" in config
    assert "manual_matches" in config
    assert "institution" in config
    # institution has specific allowed columns (not None/*)
    assert config["institution"] is not None
    assert "file_id" in config["institution"]

    # Test full schema invocation
    full_schema = get_schemas.invoke({})
    assert "SYNCHRONO DATABASE SCHEMA" in full_schema
    assert "manual_matches" in full_schema
    assert "qa/grade_b_warm" in full_schema

    # Test filtered table invocation (on-demand context)
    filtered = get_schemas.invoke({"table_names": ["manual_matches"]})
    assert "TABLE: manual_matches" in filtered
    assert "TABLE: uploaded_files" not in filtered

def test_pii_double_protection():
    from chatbot.middlewares.pii import PIIMiddleware
    from langchain.messages import HumanMessage, AIMessage
    
    pii = PIIMiddleware(pii_type="nik", detector=r"\b\d{16}\b", strategy="mask")
    
    # 1. Incoming (before_agent) protection
    human_msg = HumanMessage("Tolong cek NIK 3171012345678901 milik Yuni Ayu")
    state_in = {"messages": [human_msg]}
    res_in = pii.before_agent(state_in, runtime=None)
    assert "3171012345678901" not in res_in["messages"][0].content
    assert "*************901" in res_in["messages"][0].content

    # 2. Outgoing (after_agent) protection
    ai_msg = AIMessage("Data ditemukan dengan NIK 3271019876543210 atas nama John")
    state_out = {"messages": [ai_msg]}
    res_out = pii.after_agent(state_out, runtime=None)
    assert "3271019876543210" not in res_out["messages"][0].content
    assert "*************210" in res_out["messages"][0].content


