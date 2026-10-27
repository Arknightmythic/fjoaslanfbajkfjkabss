from datetime import datetime
from unittest.mock import ANY, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.api.routers import documents
from src.databases.internal.models import KnowledgeDocument, KnowledgeIndexState
from src.tasks import documents as document_tasks


def create_test_client():
    app = FastAPI()
    app.include_router(documents.router)
    return TestClient(app)


def test_upload_saves_object_then_enqueues_celery_job():
    client = create_test_client()
    session = MagicMock()
    uploaded = {}
    s3 = MagicMock()
    index_state = KnowledgeIndexState(source_type="faq", active_version=1, next_version=2)

    def upload_fileobj(fileobj, bucket, key):
        uploaded.update(bucket=bucket, key=key, body=fileobj.read())

    s3.upload_fileobj.side_effect = upload_fileobj
    task = MagicMock(id="celery-task-1")

    with (
        patch("src.api.routers.documents.SessionLocal", return_value=session),
        patch("src.api.routers.documents.get_s3_client", return_value=s3),
        patch("src.api.routers.documents.ensure_bucket_exists", return_value="chatbot-documents"),
        patch("src.api.routers.documents.get_or_create_index_state", return_value=index_state),
        patch("src.api.routers.documents.ingest_uploaded_document.apply_async", return_value=task) as enqueue,
    ):
        response = client.post(
            "/api/v1/knowledge/documents",
            files={"file": ("faq.md", b"Q: Apa syarat?\n\nJawaban: Bawa KK.", "text/markdown")},
        )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["task_id"] == "celery-task-1"
    assert body["source_type"] == "faq"
    assert uploaded["bucket"] == "chatbot-documents"
    assert uploaded["key"].startswith(f"faq-inbox/v2/{body['document_id']}/faq.md")
    assert body["version_number"] == 2
    assert uploaded["body"] == b"Q: Apa syarat?\n\nJawaban: Bawa KK."
    enqueue.assert_called_once_with(args=[body["document_id"]])


def test_upload_routes_general_document_to_separate_prefix_and_version():
    client = create_test_client()
    session = MagicMock()
    uploaded = {}
    s3 = MagicMock()
    index_state = KnowledgeIndexState(source_type="document", active_version=0, next_version=1)
    task = MagicMock(id="celery-task-2")

    def upload_fileobj(fileobj, bucket, key):
        uploaded.update(bucket=bucket, key=key, body=fileobj.read())

    s3.upload_fileobj.side_effect = upload_fileobj

    with (
        patch("src.api.routers.documents.SessionLocal", return_value=session),
        patch("src.api.routers.documents.get_s3_client", return_value=s3),
        patch("src.api.routers.documents.ensure_bucket_exists", return_value="chatbot-documents"),
        patch("src.api.routers.documents.get_or_create_index_state", return_value=index_state),
        patch("src.api.routers.documents.ingest_uploaded_document.apply_async", return_value=task),
    ):
        response = client.post(
            "/api/v1/knowledge/documents",
            files={"file": ("sop.pdf", b"%PDF-document", "application/pdf")},
            data={"source_type": "document"},
        )

    assert response.status_code == 202
    body = response.json()
    assert body["source_type"] == "document"
    assert body["version_number"] == 1
    assert uploaded["key"].startswith(f"document-inbox/v1/{body['document_id']}/sop.pdf")


def test_upload_rejects_unknown_source_type():
    client = create_test_client()
    with patch("src.api.routers.documents.get_s3_client") as get_s3:
        response = client.post(
            "/api/v1/knowledge/documents",
            files={"file": ("faq.md", b"Q: Test?\n\nJawaban: Test.", "text/markdown")},
            data={"source_type": "spreadsheet"},
        )

    assert response.status_code == 400
    assert "source_type" in response.json()["detail"]
    get_s3.assert_not_called()


def test_upload_rejects_unsupported_and_empty_files():
    client = create_test_client()
    with patch("src.api.routers.documents.get_s3_client") as get_s3:
        unsupported = client.post(
            "/api/v1/knowledge/documents",
            files={"file": ("faq.docx", b"not supported", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        empty = client.post(
            "/api/v1/knowledge/documents",
            files={"file": ("empty.md", b"", "text/markdown")},
        )

    assert unsupported.status_code == 415
    assert empty.status_code == 400
    get_s3.assert_not_called()


def test_pdf_extension_is_accepted_for_document_upload():
    assert documents._clean_filename("faq-reference.pdf") == "faq-reference.pdf"
    with pytest.raises(HTTPException) as exc:
        documents._clean_filename("faq-reference.docx")
    assert exc.value.status_code == 415


def test_status_endpoint_returns_document_progress():
    client = create_test_client()
    doc = KnowledgeDocument(
        id="doc-1",
        original_filename="faq.md",
        object_key="knowledge/doc-1/faq.md",
        content_type="text/markdown",
        file_size=10,
        checksum_sha256="a" * 64,
        source_type="faq",
        status="completed",
        chunk_count=2,
        created_at=datetime(2026, 10, 26, 1, 0),
    )
    session = MagicMock()
    session.get.return_value = doc

    with patch("src.api.routers.documents.SessionLocal", return_value=session):
        response = client.get("/api/v1/knowledge/documents/doc-1")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["source_type"] == "faq"
    assert response.json()["chunk_count"] == 2
    assert response.json()["created_at_wib"] == "2026-10-26T08:00:00+07:00"


def test_status_endpoint_exposes_wib_chunk_metadata():
    client = create_test_client()
    doc = KnowledgeDocument(
        id="doc-chunks",
        original_filename="sop.md",
        object_key="document-inbox/v1/doc-chunks/sop.md",
        content_type="text/markdown",
        file_size=10,
        checksum_sha256="a" * 64,
        source_type="document",
        version_number=1,
        status="completed",
    )
    session = MagicMock()
    session.get.return_value = doc
    result = MagicMock()
    result.fetchall.return_value = [
        (
            {
                "faq": 1,
                "document_id": "doc-chunks",
                "document_version": 1,
                "source_file": "sop.md",
                "ingested_at_wib": "2026-10-26T09:15:00+07:00",
                "chunk_hash": "c" * 64,
            },
            "Isi SOP",
        )
    ]
    session.execute.return_value = result

    with patch("src.api.routers.documents.SessionLocal", return_value=session):
        response = client.get("/api/v1/knowledge/documents/doc-chunks/chunks")

    assert response.status_code == 200
    body = response.json()
    assert body["chunk_count"] == 1
    assert body["chunks"][0]["ingested_at_wib"] == "2026-10-26T09:15:00+07:00"
    assert body["chunks"][0]["document_id"] == "doc-chunks"


def test_worker_downloads_from_s3_and_calls_existing_ingestor():
    doc = KnowledgeDocument(
        id="doc-2",
        original_filename="faq.md",
        object_key="faq-inbox/v2/doc-2/faq.md",
        content_type="text/markdown",
        file_size=10,
        checksum_sha256="",
        source_type="faq",
        version_number=2,
        status="queued",
    )
    content = b"Q: Test?\n\nJawaban: Berhasil."
    import hashlib

    doc.checksum_sha256 = hashlib.sha256(content).hexdigest()
    session = MagicMock()
    session.get.return_value = doc
    index_state = KnowledgeIndexState(source_type="faq", active_version=1, next_version=3)
    count_result = MagicMock()
    count_result.scalar_one.return_value = 1
    prune_result = MagicMock()
    prune_result.rowcount = 6
    session.execute.side_effect = [count_result, prune_result]
    s3 = MagicMock()

    def download_fileobj(bucket, key, destination):
        assert bucket == "chatbot-documents"
        assert key == doc.object_key
        destination.write(content)

    s3.download_fileobj.side_effect = download_fileobj
    ingestor = MagicMock()
    ingestor.is_ready = True
    ingestor.ingest_file.return_value = {"status": "success", "new_chunks": 1, "cache_cleared": True}

    with (
        patch("src.tasks.documents.SessionLocal", return_value=session),
        patch("src.tasks.documents.get_s3_client", return_value=s3),
        patch("src.tasks.documents.ensure_bucket_exists", return_value="chatbot-documents"),
        patch("src.tasks.documents.Ingestor", return_value=ingestor),
        patch("src.tasks.documents.get_or_create_index_state", return_value=index_state),
        patch("src.tasks.documents.SemanticCache") as cache_class,
    ):
        result = document_tasks.ingest_uploaded_document.apply(args=[doc.id]).get()

    assert result["status"] == "completed"
    assert result["chunk_count"] == 1
    assert doc.status == "completed"
    assert doc.chunk_count == 1
    ingestor.ingest_file.assert_called_once_with(
        ANY,
        faq_version=2,
        clear_cache=False,
        source_type="faq",
        document_id=doc.id,
        document_version=2,
        ingested_at_wib=ANY,
    )
    assert index_state.active_version == 2
    cache_class.assert_called_once_with()
    cache_class.return_value.clear.assert_called_once()


def test_worker_indexes_document_source_and_clears_document_cache():
    doc = KnowledgeDocument(
        id="doc-general",
        original_filename="sop.md",
        object_key="document-inbox/v1/doc-general/sop.md",
        content_type="text/markdown",
        file_size=10,
        checksum_sha256="",
        source_type="document",
        version_number=1,
        status="queued",
    )
    content = b"# SOP\n\nIkuti langkah-langkahnya."
    import hashlib

    doc.checksum_sha256 = hashlib.sha256(content).hexdigest()
    session = MagicMock()
    session.get.return_value = doc
    index_state = KnowledgeIndexState(source_type="document", active_version=0, next_version=2)
    count_result = MagicMock()
    count_result.scalar_one.return_value = 3
    prune_result = MagicMock()
    prune_result.rowcount = 0
    session.execute.side_effect = [count_result, prune_result]
    s3 = MagicMock()

    def download_fileobj(bucket, key, destination):
        destination.write(content)

    s3.download_fileobj.side_effect = download_fileobj
    ingestor = MagicMock()
    ingestor.is_ready = True
    ingestor.ingest_file.return_value = {"status": "success", "new_chunks": 3, "cache_cleared": False}

    with (
        patch("src.tasks.documents.SessionLocal", return_value=session),
        patch("src.tasks.documents.get_s3_client", return_value=s3),
        patch("src.tasks.documents.ensure_bucket_exists", return_value="chatbot-documents"),
        patch("src.tasks.documents.Ingestor", return_value=ingestor) as ingestor_class,
        patch("src.tasks.documents.get_or_create_index_state", return_value=index_state),
        patch("src.tasks.documents.SemanticCache") as cache_class,
    ):
        result = document_tasks.ingest_uploaded_document.apply(args=[doc.id]).get()

    assert result["status"] == "completed"
    assert result["chunk_count"] == 3
    ingestor_class.assert_called_once_with(collection_name="synchrono_documents")
    assert index_state.active_version == 1
    cache_class.assert_called_once_with(scope="document")
    cache_class.return_value.clear.assert_called_once()


def test_worker_refuses_document_outside_allowed_ingest_prefix():
    doc = KnowledgeDocument(
        id="doc-outside-prefix",
        original_filename="faq.md",
        object_key="other-folder/doc-outside-prefix/faq.md",
        content_type="text/markdown",
        file_size=10,
        checksum_sha256="a" * 64,
        source_type="faq",
        version_number=2,
        status="queued",
    )
    session = MagicMock()
    session.get.return_value = doc
    cleanup_result = MagicMock()
    cleanup_result.rowcount = 0
    session.execute.return_value = cleanup_result

    with (
        patch("src.tasks.documents.SessionLocal", return_value=session),
        patch(
            "src.tasks.documents.get_or_create_index_state",
            return_value=KnowledgeIndexState(source_type="faq", active_version=1, next_version=3),
        ),
    ):
        result = document_tasks.ingest_uploaded_document.apply(args=[doc.id], throw=False)

    assert result.failed()
    assert "outside the configured ingestion prefix" in str(result.result)
    assert doc.status == "failed"
