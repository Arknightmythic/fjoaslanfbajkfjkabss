from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from src.knowledge.document_service import (
    get_active_document_version,
    retrieve_platform_document_chunks,
)
from src.knowledge.source_types import DOCUMENT, collection_name_for


def test_retrieve_document_chunks_uses_active_version_and_reranks():
    documents = [
        Document(page_content="Chunk rendah", metadata={"source_file": "sop.md", "faq": 1}),
        Document(page_content="Chunk tinggi", metadata={"source_file": "sop.md", "faq": 2}),
        Document(page_content="Chunk negatif", metadata={"source_file": "lama.md", "faq": 0}),
    ]
    retriever = MagicMock()
    retriever.search.return_value = documents
    reranker = MagicMock()
    reranker.rerank.return_value = [0.2, 0.9, -0.5]

    with patch("src.knowledge.document_service.get_active_document_version", return_value=3):
        with patch("src.knowledge.document_service.KnowledgeRetriever", return_value=retriever) as retriever_cls:
            with patch("src.knowledge.document_service.get_reranker", return_value=reranker):
                results = retrieve_platform_document_chunks("Apa isi SOP?", k=2)

    retriever_cls.assert_called_once_with(collection_name=collection_name_for(DOCUMENT))
    retriever.search.assert_called_once_with(
        "Apa isi SOP?",
        k=20,
        filter={"faq_version": 3},
    )
    assert [result["content"] for result in results] == ["Chunk tinggi", "Chunk rendah"]
    assert results[0]["source"] == "sop.md"
    assert results[0]["score"] == 0.9


def test_retrieve_document_chunks_without_active_version_skips_search():
    with patch("src.knowledge.document_service.get_active_document_version", return_value=0):
        with patch("src.knowledge.document_service.KnowledgeRetriever") as retriever_cls:
            assert retrieve_platform_document_chunks("Apa isi SOP?") == []

    retriever_cls.assert_not_called()


def test_retrieve_document_chunks_summary_falls_back_to_document_order():
    retriever = MagicMock()
    retriever.search.return_value = [
        Document(page_content="Chunk jauh", metadata={"source_file": "sop.md", "faq": 2})
    ]
    reranker = MagicMock()
    reranker.rerank.return_value = [-4.0]
    ordered_chunks = [
        {"content": "Judul SOP", "source": "sop.md", "chunk": 0, "content_type": "text", "score": 0.0},
        {"content": "Tujuan SOP", "source": "sop.md", "chunk": 1, "content_type": "text", "score": 0.0},
    ]

    with patch("src.knowledge.document_service.get_active_document_version", return_value=3):
        with patch("src.knowledge.document_service.KnowledgeRetriever", return_value=retriever):
            with patch("src.knowledge.document_service.get_reranker", return_value=reranker):
                with patch(
                    "src.knowledge.document_service._list_active_document_chunks",
                    return_value=ordered_chunks,
                ) as list_chunks:
                    results = retrieve_platform_document_chunks("Apa isi file yang saya upload?", k=2)

    list_chunks.assert_called_once_with(3, 2)
    assert results == ordered_chunks


def test_retrieve_document_chunks_specific_question_does_not_fall_back():
    retriever = MagicMock()
    retriever.search.return_value = [
        Document(page_content="Chunk tidak relevan", metadata={"source_file": "sop.md", "faq": 2})
    ]
    reranker = MagicMock()
    reranker.rerank.return_value = [-4.0]

    with patch("src.knowledge.document_service.get_active_document_version", return_value=3):
        with patch("src.knowledge.document_service.KnowledgeRetriever", return_value=retriever):
            with patch("src.knowledge.document_service.get_reranker", return_value=reranker):
                with patch("src.knowledge.document_service._list_active_document_chunks") as list_chunks:
                    results = retrieve_platform_document_chunks(
                        "Berapa denda keterlambatan dalam dokumen SOP?", k=2
                    )

    list_chunks.assert_not_called()
    assert results == []


def test_get_active_document_version_reads_index_state():
    state = MagicMock(active_version=7)
    session = MagicMock()
    session.get.return_value = state

    with patch("src.knowledge.document_service.SessionLocal", return_value=session):
        assert get_active_document_version() == 7

    session.get.assert_called_once()
    session.close.assert_called_once()


def test_get_active_document_version_defaults_to_zero():
    session = MagicMock()
    session.get.return_value = None

    with patch("src.knowledge.document_service.SessionLocal", return_value=session):
        assert get_active_document_version() == 0

    session.close.assert_called_once()
