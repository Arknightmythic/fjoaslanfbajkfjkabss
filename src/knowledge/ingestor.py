import hashlib
import json
import os
from pathlib import Path
from typing import Optional, Union, Any, List
from dotenv import load_dotenv
from loguru import logger
from langchain_core.documents import Document
from langchain_postgres import PGVector

from src.databases.internal.config import INTERNAL_DB_URL, engine
from src.handler import _get_default_embedding
from src.knowledge.parser import clean_markdown
from src.semantic_cache import SemanticCache

load_dotenv()


class Ingestor:
    def __init__(
        self,
        vector_store: Optional[PGVector] = None,
        embedding: Optional[Any] = None,
        semantic_cache: Optional[SemanticCache] = None,
        connection: Optional[Any] = None,
        collection_name: Optional[str] = None,
    ):
        self._embedding = embedding if embedding is not None else _get_default_embedding()
        self._collection_name = collection_name or os.getenv("PGVECTOR_COLLECTION_NAME", "synchrono_faq_docs")
        self._engine = connection or engine

        # 1. Initialize Semantic Cache
        if semantic_cache is not None:
            self._semantic_cache = semantic_cache
        else:
            try:
                self._semantic_cache = SemanticCache(
                    embedding=self._embedding,
                    max_distance=float(os.getenv("SEMANTIC_CACHE_DISTANCE", "0.10")),
                    min_confidence=float(os.getenv("SEMANTIC_CACHE_MIN_CONFIDENCE", "0.90")),
                )
            except Exception as e:
                logger.warning(f"[Ingestor] Semantic cache not initialized: {e}")
                self._semantic_cache = None

        # 2. Initialize PGVector Vector Store
        if vector_store is not None:
            self._vector_store = vector_store
        else:
            try:
                self._vector_store = PGVector(
                    embeddings=self._embedding,
                    connection=self._engine,
                    collection_name=self._collection_name,
                    use_jsonb=True,
                    create_extension=True,
                )
            except Exception as e:
                logger.warning(f"[Ingestor] Failed to initialize PGVector with database engine: {e}")
                self._vector_store = None

        # 3. Load already processed hashes
        self._processed_file_hashes, self._processed_chunk_hashes = self._get_exists_hashed()

    def _get_exists_hashed(self) -> tuple[set, set]:
        processed_file_hashes = set()
        processed_chunk_hashes = set()

        if not self._engine:
            return processed_file_hashes, processed_chunk_hashes

        try:
            from sqlalchemy import text
            with self._engine.connect() as conn:
                stmt = text("SELECT cmetadata FROM langchain_pg_embedding")
                result = conn.execute(stmt)
                for row in result:
                    raw_meta = row[0]
                    if not raw_meta:
                        continue
                    meta = raw_meta if isinstance(raw_meta, dict) else json.loads(raw_meta)
                    f_hash = meta.get("file_hash")
                    c_hash = meta.get("chunk_hash")
                    if f_hash:
                        processed_file_hashes.add(f_hash)
                    if c_hash:
                        processed_chunk_hashes.add(c_hash)
        except Exception as e:
            logger.debug(f"[Ingestor] Note: Existing hash query skipped (table may not exist yet): {e}")

        return processed_file_hashes, processed_chunk_hashes

    def _compute_file_hash(self, file_path: Path) -> str:
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def ingest_file(self, file_path: Union[str, Path]) -> dict:
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        file_hash = self._compute_file_hash(file_path)

        # Level 1: File-Level Check
        if file_hash in self._processed_file_hashes:
            logger.info(f"[Ingestor] File {file_path.name} unchanged (hash matched). Skipping ingestion.")
            return {
                "file": file_path.name,
                "status": "skipped",
                "reason": "file_hash_match",
                "new_chunks": 0,
                "cache_cleared": False,
            }

        path_str = str(file_path).lower()
        if "markdown" in path_str or ".md" in path_str:
            content_type = "text"
            doc_name = file_path.name
        elif "tables" in path_str:
            content_type = "tables"
            doc_name = file_path.parent.name
        elif "images" in path_str:
            content_type = "image"
            doc_name = file_path.parent.name
        else:
            content_type = "text"
            doc_name = file_path.name

        content = file_path.read_text(encoding="utf-8")
        return self._ingest_content(
            content=content,
            doc_name=doc_name,
            content_type=content_type,
            file_hash=file_hash,
            source_file=file_path.name,
        )

    def ingest_text(self, content: str, doc_name: str = "custom_document.md") -> dict:
        file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if file_hash in self._processed_file_hashes:
            logger.info(f"[Ingestor] Content for {doc_name} unchanged (hash matched). Skipping ingestion.")
            return {
                "file": doc_name,
                "status": "skipped",
                "reason": "content_hash_match",
                "new_chunks": 0,
                "cache_cleared": False,
            }

        return self._ingest_content(
            content=content,
            doc_name=doc_name,
            content_type="text",
            file_hash=file_hash,
            source_file=doc_name,
        )

    def _ingest_content(
        self,
        content: str,
        doc_name: str,
        content_type: str,
        file_hash: str,
        source_file: str,
    ) -> dict:
        base_metadata = {
            "doc_name": doc_name,
            "content_type": content_type,
            "file_hash": file_hash,
            "source_file": source_file,
        }

        pages = clean_markdown(content)
        documents = []

        for idx, page in enumerate(pages, start=1):
            chunk_hash = hashlib.sha256(page.encode("utf-8")).hexdigest()

            # Level 2: Chunk-Level Check
            if chunk_hash in self._processed_chunk_hashes:
                logger.debug(f"[Ingestor] FAQ #{idx} already exists in vector store. Skipping duplicate.")
                continue

            metadata = base_metadata.copy()
            metadata.update({
                "faq": idx,
                "chunk_hash": chunk_hash,
            })
            documents.append(Document(page_content=page, metadata=metadata))

        if not documents:
            logger.info(f"[Ingestor] No new document chunks to add from {source_file}.")
            self._processed_file_hashes.add(file_hash)
            return {
                "file": source_file,
                "status": "no_new_chunks",
                "new_chunks": 0,
                "cache_cleared": False,
            }

        # Ingest to PGVector
        if self._vector_store is not None:
            logger.info(f"[Ingestor] Adding {len(documents)} new chunks to PGVector collection '{self._collection_name}'...")
            self._vector_store.add_documents(documents)
        else:
            logger.warning("[Ingestor] Vector store is not connected; simulated ingestion mode.")

        # Update in-memory hash tracking
        self._processed_file_hashes.add(file_hash)
        for doc in documents:
            self._processed_chunk_hashes.add(doc.metadata["chunk_hash"])

        # CONDITION: when there is a new ingestment, clear all the cache!
        cache_cleared = False
        if self._semantic_cache is not None:
            cleared_items = self._semantic_cache.clear()
            cache_cleared = True
            logger.info(
                f"[Ingestor] Ingested {len(documents)} new chunks from {source_file}. "
                f"Cleared all semantic cache (cleared {cleared_items} items/index)."
            )

        return {
            "file": source_file,
            "status": "success",
            "new_chunks": len(documents),
            "cache_cleared": cache_cleared,
        }

    def ingest_directory(
        self,
        directory_path: Union[str, Path],
        pattern: str = "*.md"
    ) -> List[dict]:
        dir_path = Path(directory_path)
        if not dir_path.is_dir():
            raise NotADirectoryError(f"Directory not found: {dir_path}")

        results = []
        for file_path in dir_path.glob(pattern):
            if file_path.is_file():
                res = self.ingest_file(file_path)
                results.append(res)
        return results


if __name__ == "__main__":
    default_faq_path = Path(__file__).parent / "faq" / "dukcapil_faq.md"
    if default_faq_path.exists():
        ingestor = Ingestor()
        summary = ingestor.ingest_file(default_faq_path)
        print(f"Ingestion result: {summary}")
    else:
        print(f"Default FAQ path not found: {default_faq_path}")
