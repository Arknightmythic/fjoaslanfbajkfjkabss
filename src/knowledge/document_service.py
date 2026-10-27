"""Semantic retrieval for the versioned general-document knowledge collection."""

import os

from loguru import logger
from sqlalchemy import text

from src.databases.internal.config import SessionLocal
from src.databases.internal.models import KnowledgeIndexState
from src.knowledge.question_routing import is_document_summary_question
from src.knowledge.reranking import get_reranker
from src.knowledge.retriever import KnowledgeRetriever
from src.knowledge.source_types import DOCUMENT, collection_name_for


DOCUMENT_DIRECT_MIN_SCORE = float(os.getenv("DOCUMENT_DIRECT_MIN_SCORE", "0.0"))
DOCUMENT_RETRIEVAL_CANDIDATES = int(os.getenv("DOCUMENT_RETRIEVAL_CANDIDATES", "20"))


def get_active_document_version() -> int:
    session = SessionLocal()
    try:
        state = session.get(KnowledgeIndexState, DOCUMENT)
        return int(state.active_version) if state is not None else 0
    finally:
        session.close()


def _list_active_document_chunks(active_version: int, k: int) -> list[dict[str, str | int | float]]:
    """Return the first chunks of the active snapshot in document order."""
    session = SessionLocal()
    try:
        rows = session.execute(
            text(
                """SELECT e.document, e.cmetadata
                   FROM langchain_pg_embedding e
                   JOIN langchain_pg_collection c ON c.uuid = e.collection_id
                   WHERE c.name = :collection_name
                     AND e.cmetadata ->> 'faq_version' = :faq_version
                   ORDER BY (e.cmetadata ->> 'faq')::int ASC
                   LIMIT :limit"""
            ),
            {
                "collection_name": collection_name_for(DOCUMENT),
                "faq_version": str(active_version),
                "limit": k,
            },
        ).fetchall()
    finally:
        session.close()

    results: list[dict[str, str | int | float]] = []
    for document, metadata in rows:
        metadata = metadata or {}
        content = str(document or "").strip()
        if not content:
            continue
        results.append(
            {
                "content": content,
                "source": str(
                    metadata.get("source_file")
                    or metadata.get("doc_name")
                    or "Dokumen"
                ),
                "chunk": int(metadata.get("faq") or 0),
                "content_type": str(metadata.get("content_type") or "text"),
                "score": 0.0,
            }
        )
    return results


def retrieve_platform_document_chunks(question: str, k: int = 4) -> list[dict[str, str | int | float]]:
    """Return the most relevant chunks from the active document snapshot."""
    active_version = get_active_document_version()
    if active_version <= 0:
        return []

    retriever = KnowledgeRetriever(collection_name=collection_name_for(DOCUMENT))
    candidates = retriever.search(
        question,
        k=max(DOCUMENT_RETRIEVAL_CANDIDATES, k * 4),
        filter={"faq_version": active_version},
    )

    results: list[dict[str, str | int | float]] = []
    if candidates:
        scores = list(get_reranker().rerank(question, [doc.page_content for doc in candidates]))
        ranked = sorted(zip(scores, candidates), key=lambda item: float(item[0]), reverse=True)
        logger.info(
            "Document rerank candidates for active_version={}: {}",
            active_version,
            [
                (
                    round(float(score), 4),
                    document.metadata.get("source_file"),
                    document.metadata.get("faq"),
                )
                for score, document in ranked[:5]
            ],
        )
        for score, document in ranked:
            numeric_score = float(score)
            content = document.page_content.strip()
            if numeric_score < DOCUMENT_DIRECT_MIN_SCORE or not content:
                continue
            results.append(
                {
                    "content": content,
                    "source": str(
                        document.metadata.get("source_file")
                        or document.metadata.get("doc_name")
                        or "Dokumen"
                    ),
                    "chunk": int(document.metadata.get("faq") or 0),
                    "content_type": str(document.metadata.get("content_type") or "text"),
                    "score": numeric_score,
                }
            )
            if len(results) >= k:
                break

    if not results and is_document_summary_question(question):
        return _list_active_document_chunks(active_version, k)
    return results
