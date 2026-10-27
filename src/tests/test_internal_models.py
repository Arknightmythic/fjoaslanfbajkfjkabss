from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from src.databases.internal.models import (
    Base,
    Conversation,
    AnswerAudit,
    KnowledgeDocument,
    KnowledgeIndexState,
    Message,
    User,
)


def _sqlite_engine_with_foreign_keys():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return engine


def test_models_share_current_metadata_and_tables():
    expected_tables = {
        "users",
        "conversations",
        "messages",
        "ref_grades",
        "ref_sync_statuses",
        "ref_process",
        "ref_match_results",
        "uploaded_files",
        "manual_matches",
        "institution",
        "knowledge_documents",
        "knowledge_index_state",
        "answer_audits",
    }

    assert expected_tables.issubset(set(Base.metadata.tables))
    assert KnowledgeDocument.__module__ == "src.databases.internal.models.knowledge_document"
    assert KnowledgeIndexState.__module__ == "src.databases.internal.models.knowledge_index_state"
    assert AnswerAudit.__module__ == "src.databases.internal.models.answer_audit"


def test_knowledge_document_source_type_columns_and_indexes():
    table = KnowledgeDocument.__table__

    assert table.c.source_type.nullable is False
    assert table.c.version_number.nullable is False
    assert table.c.status.nullable is False

    indexed_columns = {
        column.name
        for index in table.indexes
        for column in index.columns
    }
    assert {"checksum_sha256", "source_type", "status", "celery_task_id"}.issubset(indexed_columns)


def test_answer_audit_round_trip():
    engine = _sqlite_engine_with_foreign_keys()
    session = sessionmaker(bind=engine)()
    try:
        audit = AnswerAudit(
            user_id="user-1",
            thread_id="thread-1",
            route="faq_synthesized",
            question="Apa itu Grade A?",
            answer="Grade A adalah kualitas terbaik.",
            confidence_score=0.88,
            retrieval_score=2.0,
            source_count=1,
        )
        session.add(audit)
        session.commit()
        session.refresh(audit)

        assert audit.id
        assert audit.route == "faq_synthesized"
        assert audit.confidence_score == 0.88
        assert audit.retrieval_score == 2.0
    finally:
        session.close()
        engine.dispose()


def test_conversation_and_message_round_trip_with_cascade_delete():
    engine = _sqlite_engine_with_foreign_keys()
    session = sessionmaker(bind=engine)()
    try:
        session.add(User(id="user-1"))
        session.flush()
        session.add(
            Conversation(
                id="conv-1",
                user_id="user-1",
                thread_id="thread-1",
                title="Analisis Data",
            )
        )
        session.add_all(
            [
                Message(conversation_id="conv-1", role="user", content="Halo"),
                Message(conversation_id="conv-1", role="ai", content="Hai"),
            ]
        )
        session.commit()

        conversation = session.get(Conversation, "conv-1")
        assert conversation is not None
        assert conversation.thread_id == "thread-1"

        messages = session.scalars(
            select(Message).where(Message.conversation_id == "conv-1").order_by(Message.created_at)
        ).all()
        assert [message.role for message in messages] == ["user", "ai"]

        session.delete(conversation)
        session.commit()

        assert session.get(Conversation, "conv-1") is None
        assert session.scalars(select(Message).where(Message.conversation_id == "conv-1")).all() == []
    finally:
        session.close()
        engine.dispose()


def test_knowledge_document_defaults_match_faq_snapshot_contract():
    engine = _sqlite_engine_with_foreign_keys()
    session = sessionmaker(bind=engine)()
    try:
        document = KnowledgeDocument(
            id="doc-1",
            original_filename="faq.md",
            object_key="faq-inbox/v1/doc-1/faq.md",
            content_type="text/markdown",
            file_size=12,
            checksum_sha256="a" * 64,
        )
        session.add(document)
        session.commit()

        assert document.source_type == "faq"
        assert document.version_number == 1
        assert document.status == "uploaded"
        assert document.retry_count == 0
        assert document.chunk_count == 0
    finally:
        session.close()
        engine.dispose()
