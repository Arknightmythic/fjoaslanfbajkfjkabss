from datetime import datetime
import os
from pathlib import Path, PurePosixPath
import tempfile
import hashlib

from celery.utils.log import get_task_logger
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy.exc import OperationalError
from sqlalchemy import text

from src.celery_app import celery_app
from src.databases.internal.config import SessionLocal
from src.databases.internal.index_state import get_or_create_index_state
from src.databases.internal.models import KnowledgeDocument
from src.knowledge.ingestor import Ingestor
from src.knowledge.source_types import DOCUMENT, FAQ, collection_name_for, ingest_prefix_for, normalize_source_type
from src.storage.seaweedfs import ensure_bucket_exists, get_s3_client
from src.semantic_cache import SemanticCache
from src.observability.file_tracer import LocalFileTracer
from src.time_utils import now_wib

logger = get_task_logger(__name__)
TRANSIENT_ERRORS = (BotoCoreError, ClientError, OperationalError, TimeoutError, ConnectionError)


def _safe_object_filename(filename: str) -> str:
    return PurePosixPath(filename.replace("\\", "/")).name


def _version_chunk_count(session, collection_name: str, version: int) -> int:
    result = session.execute(
        text(
            """SELECT COUNT(*)
               FROM langchain_pg_embedding e
               JOIN langchain_pg_collection c ON c.uuid = e.collection_id
               WHERE c.name = :collection_name
                 AND e.cmetadata ->> 'faq_version' = :faq_version"""
        ),
        {"collection_name": collection_name, "faq_version": str(version)},
    )
    return int(result.scalar_one())


def _delete_version_chunks(session, collection_name: str, version: int) -> int:
    result = session.execute(
        text(
            """DELETE FROM langchain_pg_embedding e
               USING langchain_pg_collection c
               WHERE c.uuid = e.collection_id
                 AND c.name = :collection_name
                 AND e.cmetadata ->> 'faq_version' = :faq_version"""
        ),
        {"collection_name": collection_name, "faq_version": str(version)},
    )
    return int(result.rowcount or 0)


def _prune_inactive_chunks(session, collection_name: str, active_version: int) -> int:
    result = session.execute(
        text(
            """DELETE FROM langchain_pg_embedding e
               USING langchain_pg_collection c
               WHERE c.uuid = e.collection_id
                 AND c.name = :collection_name
                 AND e.cmetadata ->> 'faq_version' IS DISTINCT FROM :active_version"""
        ),
        {"collection_name": collection_name, "active_version": str(active_version)},
    )
    return int(result.rowcount or 0)


@celery_app.task(
    bind=True,
    name="src.tasks.documents.ingest_uploaded_document",
    max_retries=3,
    acks_late=True,
)
def ingest_uploaded_document(self, document_id: str) -> dict:
    trace = LocalFileTracer(trace_id=document_id)
    session = SessionLocal()
    source_type: str | None = None
    try:
        document = session.get(KnowledgeDocument, document_id)
        if document is None:
            raise ValueError(f"Knowledge document {document_id} does not exist")
        if document.status == "completed":
            return {"document_id": document_id, "status": "completed", "chunk_count": document.chunk_count}

        source_type = normalize_source_type(getattr(document, "source_type", None))
        collection_name = collection_name_for(source_type)
        version = int(document.version_number)
        trace.log_event("document.job_started", document_id=document_id, source_type=source_type, faq_version=version, retry=self.request.retries)
        required_prefix = f"{ingest_prefix_for(source_type)}v{version}/{document_id}/"
        if not document.object_key.startswith(required_prefix):
            raise ValueError("Document object is outside the configured ingestion prefix")

        document.status = "processing"
        document.celery_task_id = self.request.id
        document.retry_count = self.request.retries
        document.error_message = None
        document.updated_at = datetime.utcnow()
        session.commit()

        client = get_s3_client()
        bucket = ensure_bucket_exists(client)
        safe_filename = _safe_object_filename(document.original_filename)
        trace.log_event("document.download_started", document_id=document_id, source_type=source_type, faq_version=version, bucket=bucket)
        with tempfile.TemporaryDirectory(prefix="synchrono-ingest-") as temp_dir:
            local_path = Path(temp_dir) / safe_filename
            with local_path.open("wb") as destination:
                client.download_fileobj(bucket, document.object_key, destination)

            with local_path.open("rb") as source_file:
                downloaded_checksum = hashlib.file_digest(source_file, "sha256").hexdigest()
            if downloaded_checksum != document.checksum_sha256:
                raise ValueError("Downloaded object checksum does not match uploaded document")
            trace.log_event("document.download_completed", document_id=document_id, checksum_verified=True, file_size=document.file_size)

            ingestor = Ingestor(collection_name=collection_name)
            if not ingestor.is_ready:
                raise RuntimeError("PGVector is unavailable; refusing to mark document ingested")
            trace.log_event("document.chunking_started", document_id=document_id, source_type=source_type, faq_version=version)
            ingested_at_wib = now_wib().isoformat(timespec="seconds")
            result = ingestor.ingest_file(
                local_path,
                faq_version=version,
                clear_cache=False,
                source_type=source_type,
                document_id=document_id,
                document_version=version,
                ingested_at_wib=ingested_at_wib,
            )

        version_chunks = _version_chunk_count(session, collection_name, version)
        if version_chunks <= 0:
            raise ValueError("Index version contains no RAG chunks; the currently active version was kept")
        trace.log_event("document.chunking_completed", document_id=document_id, source_type=source_type, faq_version=version, version_chunk_count=version_chunks)

        index_state = get_or_create_index_state(session, source_type, for_update=True)
        if version < int(index_state.active_version):
            _delete_version_chunks(session, collection_name, version)
            document.status = "superseded"
            document.chunk_count = version_chunks
            document.error_message = None
            document.completed_at = datetime.utcnow()
            document.updated_at = datetime.utcnow()
            session.commit()
            return {"document_id": document_id, "status": "superseded", "chunk_count": version_chunks}

        if version > int(index_state.active_version):
            index_state.active_version = version
            index_state.updated_at = datetime.utcnow()
            session.commit()
            trace.log_event(
                "index.version_activated",
                document_id=document_id,
                source_type=source_type,
                active_version=version,
                version_chunk_count=version_chunks,
            )

            if source_type == FAQ:
                # The pointer now exposes the complete new FAQ snapshot; invalidate
                # cached answers before pruning the old physical vectors.
                cleared_items = SemanticCache().clear()
                trace.log_event("index.cache_invalidated", document_id=document_id, source_type=source_type, active_version=version, cleared_items=cleared_items)
                logger.info("Activated FAQ version=%s; cleared FAQ cache entries=%s", version, cleared_items)
            elif source_type == DOCUMENT:
                cleared_items = SemanticCache(scope=DOCUMENT).clear()
                trace.log_event("index.cache_invalidated", document_id=document_id, source_type=source_type, active_version=version, cleared_items=cleared_items)
                logger.info("Activated document version=%s; cleared document cache entries=%s", version, cleared_items)

        pruned_chunks = _prune_inactive_chunks(session, collection_name, version)
        session.commit()
        trace.log_event(
            "index.old_versions_pruned",
            document_id=document_id,
            source_type=source_type,
            active_version=version,
            pruned_chunk_count=pruned_chunks,
        )

        document.status = "completed"
        document.chunk_count = version_chunks
        document.error_message = None
        document.completed_at = datetime.utcnow()
        document.updated_at = datetime.utcnow()
        session.commit()
        trace.log_event("document.job_completed", document_id=document_id, source_type=source_type, faq_version=version, chunk_count=document.chunk_count)
        return {
            "document_id": document_id,
            "status": "completed",
            "chunk_count": document.chunk_count,
            "faq_version": version,
            "pruned_chunks": pruned_chunks,
            "ingestion": result,
        }
    except Exception as exc:
        session.rollback()
        document = session.get(KnowledgeDocument, document_id)
        if document is not None:
            document.retry_count = self.request.retries
            document.error_message = f"{type(exc).__name__}: document ingestion failed"
            document.updated_at = datetime.utcnow()
            if self.request.retries < self.max_retries and isinstance(exc, TRANSIENT_ERRORS):
                document.status = "queued"
                session.commit()
                raise self.retry(exc=exc, countdown=min(30 * (2 ** self.request.retries), 300))
            document.status = "failed"
            try:
                cleanup_source_type = normalize_source_type(getattr(document, "source_type", None))
                index_state = get_or_create_index_state(session, cleanup_source_type, for_update=True)
                if int(document.version_number) > int(index_state.active_version):
                    _delete_version_chunks(
                        session,
                        collection_name_for(cleanup_source_type),
                        int(document.version_number),
                    )
            except Exception:
                logger.exception("Failed to clean staging document version=%s", document.version_number)
            session.commit()
        trace.log_event("document.job_failed", document_id=document_id, source_type=source_type, error_type=type(exc).__name__, retry=self.request.retries)
        logger.exception("Document ingestion failed for document_id=%s", document_id)
        raise
    finally:
        session.close()
