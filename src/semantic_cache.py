from valkey.exceptions import ResponseError
from loguru import logger
import json
import logging
import os
import re
import struct
import uuid
from typing import Optional, Any, List
import valkey


class SemanticCache:
    def __init__(
        self,
        embedding=None,
        index_name: str = "idx:query_cache",
        key_prefix: str = "query_cache:",
        ttl: int = 3600,
        max_distance: float = 0.10,
        min_confidence: float = 0.90,
    ):
        host = os.getenv("VALKEY_HOST") or os.getenv("REDIS_HOST") or "127.0.0.1"
        port_env = os.getenv("VALKEY_PORT") or os.getenv("REDIS_PORT") or "6379"
        db_env = os.getenv("VALKEY_DB") or os.getenv("REDIS_DB") or "0"
        try:
            port = int(port_env)
            db = int(db_env)
        except (ValueError, TypeError):
            port = 6379
            db = 0

        self._index_name = index_name
        self._key_prefix = key_prefix
        self._ttl = ttl
        self._embedding = embedding
        self._ready = False
        self._unavailable = False

        # Thresholds: condition cache retrieve document >90% conf
        env_min_conf = os.getenv("SEMANTIC_CACHE_MIN_CONFIDENCE")
        self._min_confidence = float(env_min_conf) if env_min_conf is not None else min_confidence

        env_distance = os.getenv("SEMANTIC_CACHE_DISTANCE")
        if env_distance is not None:
            self._max_distance = float(env_distance)
        else:
            # For cosine distance, distance = 1 - similarity.
            # >90% confidence corresponds to distance < 0.10.
            self._max_distance = min(max_distance, round(1.0 - self._min_confidence, 4))

        try:
            self._client = valkey.Valkey(
                host=host,
                port=port,
                db=db,
                socket_connect_timeout=float(os.getenv("VALKEY_TIMEOUT", "1.0")),
                socket_timeout=float(os.getenv("VALKEY_TIMEOUT", "2.0")),
                decode_responses=False,
            )
        except Exception as e:
            self._client = None
            self._disable(f"Failed to initialize Valkey client: {e}")

    def get(self, query: str) -> Optional[str]:
        if not self._ensure_index():
            return None

        if not self._embedding:
            return None

        try:
            query_embedding = self._embedding.embed_query(
                self.normalize_query(query)
            )
        except Exception as e:
            logger.error(f"[VALKEY] Failed to generate query embedding: {e}")
            return None

        try:
            result = self._client.execute_command(
                "FT.SEARCH",
                self._index_name,
                "*=>[KNN 1 @embedding $query_vector AS distance]",
                "PARAMS",
                "2",
                "query_vector",
                self.vector_bytes(query_embedding),
                "RETURN",
                "2",
                "final_answer",
                "distance",
                "DIALECT",
                "2",
            )
        except ResponseError as error:
            self._disable(f"Semantic cache search failed: {error}")
            return None
        except Exception as error:
            logger.error(f"[VALKEY] Error executing search command: {error}")
            return None

        if not result or result[0] == 0:
            return None

        fields = dict(zip(result[2][::2], result[2][1::2]))
        distance_value = fields.get(b"distance", fields.get("distance"))
        answer_value = fields.get(b"final_answer", fields.get("final_answer"))
        if distance_value is None or answer_value is None:
            return None

        distance = float(distance_value)
        # Cosine distance metric: confidence = 1.0 - distance
        confidence = 1.0 - distance

        # Condition: cache retrieve document >90% conf
        if confidence <= self._min_confidence or distance > self._max_distance:
            logger.info(
                f"[VALKEY] Cache miss! Retrieved document confidence {confidence * 100:.2f}% "
                f"(distance {distance:.4f}) does not meet the >{self._min_confidence * 100:.0f}% confidence threshold."
            )
            return None

        logger.info(
            f"[VALKEY] Cache hit! Retrieved document with {confidence * 100:.2f}% confidence (>90%). "
            f"Distance: {distance:.4f} <= {self._max_distance}"
        )
        return (
            answer_value.decode("utf-8")
            if isinstance(answer_value, bytes)
            else str(answer_value)
        )

    def set(self, query: str, final_answer: str, retrieved_chunks: Optional[Any] = None) -> None:
        if not self._ensure_index():
            return

        if not self._embedding or not final_answer:
            return

        try:
            logger.info("[VALKEY] Cache is not found! Set new cache")
            normalized_query = self.normalize_query(query)
            embedding = self._embedding.embed_query(normalized_query)
            cache_key = f"{self._key_prefix}{uuid.uuid4().hex}"
            self._client.hset(
                cache_key,
                mapping={
                    "question": normalized_query,
                    "final_answer": final_answer,
                    "retrieved_chunks": json.dumps(
                        self.serialize_retrieved_chunks(retrieved_chunks) if retrieved_chunks else []
                    ),
                    "embedding": self.vector_bytes(embedding),
                },
            )
            self._client.expire(cache_key, self._ttl)
        except Exception as e:
            logger.error(f"[VALKEY] Failed to store response in semantic cache: {e}")

    def clear(self) -> int:
        """Clear all cached queries from the semantic cache."""
        if not self._client:
            return 0

        cleared_count = 0
        try:
            # 1. Drop search index with DD (Delete Documents)
            try:
                self._client.execute_command("FT.DROPINDEX", self._index_name, "DD")
                self._ready = False
                cleared_count += 1
                logger.info(f"[VALKEY] Dropped search index '{self._index_name}' and deleted documents.")
            except ResponseError:
                pass

            # 2. Delete any remaining keys matching key_prefix
            cursor = 0
            while True:
                cursor, keys = self._client.scan(cursor=cursor, match=f"{self._key_prefix}*", count=200)
                if keys:
                    deleted = self._client.delete(*keys)
                    cleared_count += deleted
                if cursor == 0:
                    break

            self._ready = False
            logger.info(f"[VALKEY] Semantic cache cleared successfully (items: {cleared_count}).")
            return cleared_count
        except Exception as e:
            logger.error(f"[VALKEY] Failed to clear semantic cache: {e}")
            return 0

    def _ensure_index(self) -> bool:
        if self._ready:
            return True
        if self._unavailable or self._client is None or self._embedding is None:
            return False

        try:
            # 1. Fast check if index already exists without calling embedding model
            try:
                self._client.execute_command("FT.INFO", self._index_name)
                self._ready = True
                return True
            except Exception:
                pass

            # 2. Get vector dimension
            dim_env = os.getenv("EMBEDDING_DIMENSION")
            if dim_env:
                dimension = int(dim_env)
            else:
                dimension = len(self._embedding.embed_query("cache dimension probe"))

            self._client.execute_command(
                "FT.CREATE",
                self._index_name,
                "ON",
                "HASH",
                "PREFIX",
                "1",
                self._key_prefix,
                "SCHEMA",
                "question",
                "TEXT",
                "final_answer",
                "TEXT",
                "embedding",
                "VECTOR",
                "HNSW",
                "6",
                "TYPE",
                "FLOAT32",
                "DIM",
                str(dimension),
                "DISTANCE_METRIC",
                "COSINE",
            )
        except ResponseError as error:
            if "already exists" not in str(error).lower():
                self._disable(f"Semantic cache index unavailable: {error}")
                return False
        except Exception as error:
            self._disable(f"Semantic cache connection failed: {error}")
            return False

        self._ready = True
        return True

    def _disable(self, message: str) -> None:
        logger.error(message)
        self._unavailable = True
        self._ready = False

    @staticmethod
    def normalize_query(query: str) -> str:
        return re.sub(r"\b\d{16}\b", "[NIK]", query.strip().lower())

    @staticmethod
    def vector_bytes(vector) -> bytes:
        return struct.pack(f"{len(vector)}f", *vector)

    @staticmethod
    def serialize_retrieved_chunks(chunks):
        if not chunks:
            return []
        serialized = []
        for item in chunks:
            if isinstance(item, tuple) and len(item) == 2:
                score, document = item
                serialized.append(
                    {
                        "score": float(score),
                        "page_content": getattr(document, "page_content", str(document)),
                        "metadata": getattr(document, "metadata", {}),
                    }
                )
            else:
                serialized.append(str(item))
        return serialized
