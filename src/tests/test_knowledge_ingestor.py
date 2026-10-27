import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from langchain_core.documents import Document

from src.knowledge.parser import chunk_document_text, clean_markdown
from src.knowledge.ingestor import Ingestor
from src.knowledge.retriever import KnowledgeRetriever
from src.semantic_cache import SemanticCache


def test_clean_markdown_parsing():
    content = """
Q: Apa syarat pembuatan KTP-el?

Syaratnya adalah membawa Kartu Keluarga (KK).

<!-- page break -->

Q: Berapa biaya pembuatan KTP-el?

Pembuatan KTP-el gratis tanpa dipungut biaya retribusi.
"""
    pages = clean_markdown(content)
    assert len(pages) == 2
    assert "<question>Apa syarat pembuatan KTP-el?</question>" in pages[0]
    assert "<answer>Syaratnya adalah membawa Kartu Keluarga (KK).</answer>" in pages[0]
    assert "<question>Berapa biaya pembuatan KTP-el?</question>" in pages[1]
    assert "<answer>Pembuatan KTP-el gratis tanpa dipungut biaya retribusi.</answer>" in pages[1]


def test_chunk_document_text_splits_long_text_with_overlap():
    text = ("A" * 700) + "\n\n" + ("B" * 700)

    chunks = chunk_document_text(text, max_chars=1000, overlap=100)

    assert len(chunks) == 2
    assert chunks[0] == "A" * 700
    assert chunks[1].startswith("A" * 100)
    assert chunks[1].endswith("B" * 700)
    assert all(len(chunk) <= 1000 for chunk in chunks)


def test_chunk_document_text_keeps_short_text_whole():
    assert chunk_document_text("Isi SOP singkat.") == ["Isi SOP singkat."]
    assert chunk_document_text("   ") == []


def test_ingestor_clears_cache_on_new_ingestion():
    """Verify that when new documents are ingested into PGVector, all semantic cache is cleared."""
    mock_vector_store = MagicMock()
    mock_cache = MagicMock(spec=SemanticCache)
    mock_embedding = MagicMock()

    ingestor = Ingestor(
        vector_store=mock_vector_store,
        embedding=mock_embedding,
        semantic_cache=mock_cache,
        connection=MagicMock(),
    )

    # Empty existing hashes
    ingestor._processed_file_hashes = set()
    ingestor._processed_chunk_hashes = set()

    sample_md = """Q: Pertanyaan Baru?
Jawaban Baru."""

    result = ingestor.ingest_text(sample_md, doc_name="test_doc.md")

    assert result["status"] == "success"
    assert result["new_chunks"] == 1
    assert result["cache_cleared"] is True

    # Check vector store was called with new Document
    assert mock_vector_store.add_documents.called
    added_docs = mock_vector_store.add_documents.call_args[0][0]
    assert len(added_docs) == 1
    assert "<question>Pertanyaan Baru?</question>" in added_docs[0].page_content

    # Check that semantic cache clear() WAS CALLED
    mock_cache.clear.assert_called_once()


def test_document_ingestion_does_not_clear_faq_cache():
    mock_vector_store = MagicMock()
    mock_cache = MagicMock(spec=SemanticCache)

    ingestor = Ingestor(
        vector_store=mock_vector_store,
        embedding=MagicMock(),
        semantic_cache=mock_cache,
        connection=MagicMock(),
    )

    result = ingestor.ingest_text(
        "Q: Apa isi SOP?\nJawaban: Ikuti langkah-langkahnya.",
        doc_name="sop.md",
        source_type="document",
    )

    assert result["status"] == "success"
    assert result["cache_cleared"] is False
    mock_cache.clear.assert_not_called()
    added_docs = mock_vector_store.add_documents.call_args[0][0]
    assert added_docs[0].metadata["source_type"] == "document"


def test_versioned_ingest_scopes_hashes_by_source_type(tmp_path):
    test_file = tmp_path / "shared.md"
    test_file.write_text("Q: Pertanyaan?\nJawaban: Sama.", encoding="utf-8")
    mock_vector_store = MagicMock()

    ingestor = Ingestor(
        vector_store=mock_vector_store,
        embedding=MagicMock(),
        semantic_cache=MagicMock(spec=SemanticCache),
        connection=MagicMock(),
    )

    faq_result = ingestor.ingest_file(test_file, faq_version=1, source_type="faq")
    document_result = ingestor.ingest_file(test_file, faq_version=1, source_type="document")

    assert faq_result["status"] == "success"
    assert faq_result["new_chunks"] == 1
    assert document_result["status"] == "success"
    assert document_result["new_chunks"] == 1
    assert ingestor._processed_versioned_file_hashes[("faq", 1)]
    assert ingestor._processed_versioned_file_hashes[("document", 1)]
    assert ingestor._processed_versioned_chunk_hashes[("faq", 1)]
    assert ingestor._processed_versioned_chunk_hashes[("document", 1)]


def test_document_chunks_store_document_id_version_and_wib_timestamp(tmp_path):
    test_file = tmp_path / "sop.md"
    test_file.write_text("# SOP\n\nIkuti langkah-langkahnya.", encoding="utf-8")
    mock_vector_store = MagicMock()
    ingestor = Ingestor(
        vector_store=mock_vector_store,
        embedding=MagicMock(),
        semantic_cache=MagicMock(spec=SemanticCache),
        connection=MagicMock(),
    )

    result = ingestor.ingest_file(
        test_file,
        faq_version=7,
        source_type="document",
        document_id="doc-7",
        document_version=7,
        ingested_at_wib="2026-10-26T09:15:00+07:00",
    )

    assert result["status"] == "success"
    metadata = mock_vector_store.add_documents.call_args[0][0][0].metadata
    assert metadata["document_id"] == "doc-7"
    assert metadata["document_version"] == 7
    assert metadata["faq_version"] == 7
    assert metadata["ingested_at_wib"] == "2026-10-26T09:15:00+07:00"


def test_ingestor_does_not_clear_cache_when_duplicate_file():
    """Verify that when a duplicate file is ingested, no new documents are added and cache is NOT cleared."""
    mock_vector_store = MagicMock()
    mock_cache = MagicMock(spec=SemanticCache)
    mock_embedding = MagicMock()

    ingestor = Ingestor(
        vector_store=mock_vector_store,
        embedding=mock_embedding,
        semantic_cache=mock_cache,
        connection=MagicMock(),
    )

    sample_md = "Q: Pertanyaan Lama?\nJawaban Lama."

    # First ingestion
    ingestor.ingest_text(sample_md, doc_name="duplicate_test.md")
    assert mock_cache.clear.call_count == 1

    # Second ingestion of the same text
    res2 = ingestor.ingest_text(sample_md, doc_name="duplicate_test.md")
    assert res2["status"] == "skipped"
    assert res2["new_chunks"] == 0
    assert res2["cache_cleared"] is False

    # Cache clear count must still be 1 (not called again)
    assert mock_cache.clear.call_count == 1


def test_ingestor_file_ingestion(tmp_path):
    """Verify file-based ingestion from disk and clearing cache."""
    test_file = tmp_path / "faq_sample.md"
    test_file.write_text("Q: Dokumen apa saja?\nSemua dokumen.", encoding="utf-8")

    mock_vector_store = MagicMock()
    mock_cache = MagicMock(spec=SemanticCache)

    ingestor = Ingestor(
        vector_store=mock_vector_store,
        embedding=MagicMock(),
        semantic_cache=mock_cache,
        connection=MagicMock(),
    )

    result = ingestor.ingest_file(test_file)
    assert result["status"] == "success"
    assert result["new_chunks"] == 1
    assert result["cache_cleared"] is True
    assert mock_cache.clear.called


def test_pdf_text_extraction_preserves_page_boundaries(tmp_path):
    pdf_file = tmp_path / "faq.pdf"
    pdf_file.write_bytes(b"%PDF-fake")
    reader = MagicMock()
    reader.pages = [MagicMock(extract_text=lambda: "Q: Apa arti grade?\nJawaban: Grade mengukur kualitas."), MagicMock(extract_text=lambda: "Q: Apa arti status?\nJawaban: Status menunjukkan proses.")]

    with patch("pypdf.PdfReader", return_value=reader):
        ingestor = Ingestor(
            vector_store=MagicMock(),
            embedding=MagicMock(),
            semantic_cache=MagicMock(spec=SemanticCache),
            connection=MagicMock(),
        )
        extracted = ingestor._read_document_text(pdf_file)

    assert "Grade mengukur kualitas." in extracted
    assert "<!-- page break -->" in extracted
    assert "Status menunjukkan proses." in extracted


def test_scanned_pdf_without_extractable_text_fails_clearly(tmp_path):
    pdf_file = tmp_path / "scanned.pdf"
    pdf_file.write_bytes(b"%PDF-fake")
    reader = MagicMock()
    reader.pages = [MagicMock(extract_text=lambda: None)]

    with patch("pypdf.PdfReader", return_value=reader):
        ingestor = Ingestor(
            vector_store=MagicMock(),
            embedding=MagicMock(),
            semantic_cache=MagicMock(spec=SemanticCache),
            connection=MagicMock(),
        )
        with pytest.raises(ValueError, match="no extractable text"):
            ingestor._read_document_text(pdf_file)


def test_knowledge_retriever_search():
    mock_vector_store = MagicMock()
    sample_doc = Document(page_content="Hasil pencarian FAQ", metadata={"source": "faq"})
    mock_vector_store.similarity_search.return_value = [sample_doc]

    retriever = KnowledgeRetriever(
        vector_store=mock_vector_store,
        embedding=MagicMock(),
    )

    results = retriever.search("syarat ktp")
    assert len(results) == 1
    assert results[0].page_content == "Hasil pencarian FAQ"
    mock_vector_store.similarity_search.assert_called_once_with(query="syarat ktp", k=5)


def test_api_ingest_endpoints():
    from fastapi.testclient import TestClient
    from src.api.server import app

    client = TestClient(app)

    # 1. Test clear-cache endpoint
    with patch("src.api.routers.ingest.SemanticCache") as mock_cache_cls:
        mock_cache = MagicMock()
        mock_cache.clear.return_value = 3
        mock_cache_cls.return_value = mock_cache

        res = client.post("/api/v1/ingest/clear-cache")
        assert res.status_code == 200
        assert res.json()["status"] == "success"
        assert res.json()["cleared_items"] == 3

    # 2. Test text ingestion endpoint
    with patch("src.api.routers.ingest.Ingestor") as mock_ingestor_cls:
        mock_ingestor = MagicMock()
        mock_ingestor.ingest_text.return_value = {"status": "success", "new_chunks": 2, "cache_cleared": True}
        mock_ingestor_cls.return_value = mock_ingestor

        res = client.post("/api/v1/ingest/text", json={"content": "Q: Pertanyaan?\n\nJawaban."})
        assert res.status_code == 200
        assert res.json()["new_chunks"] == 2
        assert res.json()["cache_cleared"] is True
