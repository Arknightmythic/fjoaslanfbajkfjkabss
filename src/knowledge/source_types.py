"""Source-type registry for isolated knowledge indexes (FAQ vs general documents)."""

import os

FAQ = "faq"
DOCUMENT = "document"
SOURCE_TYPES = (FAQ, DOCUMENT)

_COLLECTION_ENV = {
    FAQ: ("PGVECTOR_COLLECTION_NAME", "synchrono_faq_docs"),
    DOCUMENT: ("PGVECTOR_DOCUMENT_COLLECTION_NAME", "synchrono_documents"),
}
_PREFIX_ENV = {
    FAQ: ("KNOWLEDGE_INGEST_PREFIX", "faq-inbox/"),
    DOCUMENT: ("KNOWLEDGE_DOCUMENT_INGEST_PREFIX", "document-inbox/"),
}


def normalize_source_type(value: str | None) -> str:
    source_type = (value or FAQ).strip().lower()
    if source_type not in SOURCE_TYPES:
        allowed = ", ".join(SOURCE_TYPES)
        raise ValueError(f"Unsupported source_type '{value}'. Expected one of: {allowed}")
    return source_type


def collection_name_for(source_type: str) -> str:
    env_name, default = _COLLECTION_ENV[normalize_source_type(source_type)]
    return os.getenv(env_name, default)


def ingest_prefix_for(source_type: str) -> str:
    env_name, default = _PREFIX_ENV[normalize_source_type(source_type)]
    prefix = os.getenv(env_name, default).strip("/")
    if not prefix:
        raise RuntimeError(f"{env_name} must not be empty")
    return f"{prefix}/"
