"""Shared cross-encoder reranker for FAQ and general document retrieval."""

from functools import lru_cache
import os

from fastembed.rerank.cross_encoder import TextCrossEncoder


RERANKER_MODEL = os.getenv(
    "RERANKER_MODEL",
    os.getenv("FAQ_RERANKER_MODEL", "BAAI/bge-reranker-base"),
)


@lru_cache(maxsize=1)
def get_reranker() -> TextCrossEncoder:
    return TextCrossEncoder(model_name=RERANKER_MODEL)
