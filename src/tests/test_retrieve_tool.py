from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from src.knowledge.faq_service import retrieve_platform_faq_chunks


def test_platform_faq_retrieval_returns_grounding_chunks():
    document = Document(
        page_content=(
            "<question>Apakah AI menentukan status padan?</question>\n"
            "<answer>Tidak. Keputusan akhir ditentukan aturan sistem dan operator.</answer>"
        ),
        metadata={"source_file": "synchrono_platform_faq.md"},
    )
    mock_retriever = MagicMock()
    mock_retriever.search.return_value = [document]
    mock_reranker = MagicMock()
    mock_reranker.rerank.return_value = [7.5]

    with (
        patch("src.knowledge.faq_service.KnowledgeRetriever", return_value=mock_retriever),
        patch("src.knowledge.faq_service.get_active_faq_version", return_value=3),
        patch("src.knowledge.faq_service._reranker", return_value=mock_reranker),
    ):
        result = retrieve_platform_faq_chunks("Apakah AI menentukan status padan?")

    mock_retriever.search.assert_called_once_with("Apakah AI menentukan status padan?", k=20, filter={"faq_version": 3})
    assert len(result) == 1
    assert result[0]["content"] == document.page_content
    assert result[0]["answer"] == "Tidak. Keputusan akhir ditentukan aturan sistem dan operator."
    assert result[0]["matched_question"] == "Apakah AI menentukan status padan?"
    assert result[0]["source"] == "synchrono_platform_faq.md"
    assert result[0]["score"] == 7.5


def test_platform_faq_lookup_rejects_low_relevance_result():
    document = Document(
        page_content="<question>FAQ unrelated</question><answer>unrelated answer</answer>",
        metadata={"source_file": "synchrono_platform_faq.md"},
    )
    mock_retriever = MagicMock()
    mock_retriever.search.return_value = [document]
    mock_reranker = MagicMock()
    mock_reranker.rerank.return_value = [0.2]

    with (
        patch("src.knowledge.faq_service.FAQ_DIRECT_MIN_SCORE", 2.0),
        patch("src.knowledge.faq_service.KnowledgeRetriever", return_value=mock_retriever),
        patch("src.knowledge.faq_service.get_active_faq_version", return_value=3),
        patch("src.knowledge.faq_service._reranker", return_value=mock_reranker),
    ):
        assert retrieve_platform_faq_chunks("unrelated query") == []


def test_platform_faq_retrieval_returns_no_chunks_when_no_snapshot_is_active():
    retriever = MagicMock()
    with (
        patch("src.knowledge.faq_service.get_active_faq_version", return_value=0),
        patch("src.knowledge.faq_service.KnowledgeRetriever", return_value=retriever),
    ):
        assert retrieve_platform_faq_chunks("Apa peran AI?") == []
    retriever.search.assert_not_called()
