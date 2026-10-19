import os
from typing import List, Optional, Tuple, Any
from dotenv import load_dotenv
from loguru import logger
from langchain_core.documents import Document
from langchain_postgres import PGVector

from src.databases.internal.config import engine
from src.handler import _get_default_embedding

load_dotenv()


class KnowledgeRetriever:
    def __init__(
        self,
        vector_store: Optional[PGVector] = None,
        embedding: Optional[Any] = None,
        collection_name: Optional[str] = None,
    ):
        self._embedding = embedding if embedding is not None else _get_default_embedding()
        self._collection_name = collection_name or os.getenv("PGVECTOR_COLLECTION_NAME", "synchrono_faq_docs")

        if vector_store is not None:
            self._vector_store = vector_store
        else:
            try:
                self._vector_store = PGVector(
                    embeddings=self._embedding,
                    connection=engine,
                    collection_name=self._collection_name,
                    use_jsonb=True,
                    create_extension=False,
                )
            except Exception as e:
                logger.warning(f"[KnowledgeRetriever] Could not connect PGVector: {e}")
                self._vector_store = None

    def search(self, query: str, k: int = 5) -> List[Document]:
        if not self._vector_store:
            return []
        try:
            return self._vector_store.similarity_search(query=query, k=k)
        except Exception as e:
            logger.error(f"[KnowledgeRetriever] Error executing search: {e}")
            return []

    def search_with_score(self, query: str, k: int = 5) -> List[Tuple[Document, float]]:
        if not self._vector_store:
            return []
        try:
            return self._vector_store.similarity_search_with_score(query=query, k=k)
        except Exception as e:
            logger.error(f"[KnowledgeRetriever] Error executing search with score: {e}")
            return []
