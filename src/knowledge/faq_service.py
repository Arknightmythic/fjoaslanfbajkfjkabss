"""Direct, document-grounded FAQ lookup; this path does not call the chat LLM."""

import os
import re
from typing import Optional

from langchain_core.documents import Document
from loguru import logger
from src.knowledge.reranking import get_reranker
from src.knowledge.retriever import KnowledgeRetriever
from src.knowledge.source_types import FAQ
from src.databases.internal.config import SessionLocal
from src.databases.internal.models import KnowledgeIndexState


FAQ_DIRECT_MIN_SCORE = float(os.getenv("FAQ_DIRECT_MIN_SCORE", "0.0"))


def _reranker():
    return get_reranker()


def _tag_content(document: Document, tag: str) -> str:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", document.page_content, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def get_active_faq_version() -> int:
    session = SessionLocal()
    try:
        state = session.get(KnowledgeIndexState, FAQ)
        return int(state.active_version) if state is not None else 0
    finally:
        session.close()


def retrieve_platform_faq_chunks(question: str, k: int = 3) -> list[dict[str, str | float]]:
    """Return high-relevance FAQ chunks for grounded LLM answer synthesis."""
    active_version = get_active_faq_version()
    if active_version <= 0:
        return []
    retriever = KnowledgeRetriever()
    candidates = retriever.search(
        question,
        k=max(20, k * 4),
        filter={"faq_version": active_version},
    )
    if not candidates:
        return []

    scores = list(_reranker().rerank(question, [doc.page_content for doc in candidates]))
    ranked = sorted(zip(scores, candidates), key=lambda item: float(item[0]), reverse=True)
    logger.info(
        "FAQ rerank candidates for active_version=%s: %s",
        active_version,
        [(round(float(score), 4), document.metadata.get("faq"), document.metadata.get("source_file")) for score, document in ranked[:5]],
    )
    results = []
    for score, document in ranked[:k]:
        answer = _tag_content(document, "answer")
        question_text = _tag_content(document, "question")
        # PDF/TXT sources may be prose rather than explicit Q:/answer blocks.
        # Use the retrieved page as grounding context and let the LLM synthesize it.
        if not answer and not question_text:
            answer = document.page_content.strip()
            question_text = question
        numeric_score = float(score)
        if answer and question_text and numeric_score >= FAQ_DIRECT_MIN_SCORE:
            results.append({
                "content": document.page_content,
                "answer": answer,
                "matched_question": question_text,
                "source": str(document.metadata.get("source_file") or document.metadata.get("doc_name") or "FAQ"),
                "score": numeric_score,
            })
    return results
