import hashlib
import os
from pathlib import Path, PurePosixPath
import tempfile
import uuid

from celery.exceptions import CeleryError
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from datetime import datetime

from src.celery_app import celery_app
from src.databases.internal.config import SessionLocal
from src.databases.internal.index_state import get_or_create_index_state
from src.databases.internal.models import KnowledgeDocument
from src.knowledge.source_types import FAQ, collection_name_for, ingest_prefix_for, normalize_source_type
from src.storage.seaweedfs import ensure_bucket_exists, get_s3_client
from src.tasks.documents import ingest_uploaded_document
from src.observability.file_tracer import LocalFileTracer
from src.time_utils import to_wib_iso

router = APIRouter(prefix="/api/v1/knowledge/documents", tags=["knowledge documents"])
ALLOWED_EXTENSIONS = {".md", ".txt", ".pdf"}
MAX_UPLOAD_SIZE = int(os.getenv("KNOWLEDGE_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
UPLOAD_CHUNK_SIZE = 1024 * 1024


def _clean_filename(filename: str | None) -> str:
    name = PurePosixPath((filename or "document.md").replace("\\", "/")).name.strip()
    if not name or name in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Only .md, .txt, and text-based .pdf documents are supported")
    return name


async def _stage_upload(upload: UploadFile, suffix: str) -> tuple[str, int, str]:
    fd, temp_path = tempfile.mkstemp(prefix="synchrono-upload-", suffix=suffix)
    os.close(fd)
    digest = hashlib.sha256()
    size = 0
    try:
        with open(temp_path, "wb") as staged_file:
            while True:
                chunk = await upload.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_SIZE:
                    raise HTTPException(status_code=413, detail="Document exceeds the configured upload size limit")
                digest.update(chunk)
                staged_file.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="Uploaded document is empty")
        return temp_path, size, digest.hexdigest()
    except Exception:
        Path(temp_path).unlink(missing_ok=True)
        raise


def _save_status(session: Session, document: KnowledgeDocument, *, status_value: str, error: str | None = None) -> None:
    document.status = status_value
    document.error_message = error
    session.add(document)
    session.commit()


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def upload_knowledge_document(
    file: UploadFile = File(...),
    source_type: str = Form(FAQ),
):
    try:
        resolved_source_type = normalize_source_type(source_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    filename = _clean_filename(file.filename)
    temp_path, file_size, checksum = await _stage_upload(file, Path(filename).suffix.lower())
    document_id = str(uuid.uuid4())
    trace = LocalFileTracer(trace_id=document_id)
    bucket = os.getenv("S3_BUCKET", "chatbot-documents")
    content_type = file.content_type or "application/octet-stream"

    session = SessionLocal()
    document = None
    trace.log_event(
        "document.upload_started",
        document_id=document_id,
        source_type=resolved_source_type,
        extension=Path(filename).suffix.lower(),
        file_size=file_size,
    )
    try:
        index_state = get_or_create_index_state(session, resolved_source_type, for_update=True)
        version_number = index_state.next_version
        index_state.next_version += 1
        object_key = f"{ingest_prefix_for(resolved_source_type)}v{version_number}/{document_id}/{filename}"
        document = KnowledgeDocument(
            id=document_id,
            original_filename=filename,
            object_key=object_key,
            content_type=content_type,
            file_size=file_size,
            checksum_sha256=checksum,
            source_type=resolved_source_type,
            version_number=version_number,
            status="uploading",
        )
        session.add(document)
        session.commit()

        client = get_s3_client()
        await run_in_threadpool(ensure_bucket_exists, client, bucket)
        with open(temp_path, "rb") as staged_file:
            await run_in_threadpool(client.upload_fileobj, staged_file, bucket, object_key)

        _save_status(session, document, status_value="queued")
        trace.log_event("document.object_stored", document_id=document_id, source_type=resolved_source_type, faq_version=version_number, bucket=bucket)
        try:
            task = ingest_uploaded_document.apply_async(args=[document_id])
        except CeleryError as exc:
            _save_status(session, document, status_value="failed", error="Unable to enqueue document ingestion")
            logger.exception("Unable to enqueue document ingestion for document_id=%s", document_id)
            raise HTTPException(
                status_code=503,
                detail={
                    "message": "Document uploaded but ingestion queue is unavailable",
                    "document_id": document_id,
                },
            ) from exc

        session.query(KnowledgeDocument).filter_by(id=document_id).update(
            {"celery_task_id": task.id, "updated_at": datetime.utcnow()},
            synchronize_session=False,
        )
        session.commit()
        session.refresh(document)
        trace.log_event("document.job_queued", document_id=document_id, source_type=resolved_source_type, task_id=task.id, faq_version=version_number)
        return {
            "document_id": document.id,
            "task_id": task.id,
            "filename": document.original_filename,
            "source_type": document.source_type,
            "version_number": document.version_number,
            "status": document.status,
        }
    except HTTPException:
        trace.log_event("document.upload_rejected", document_id=document_id, error_type="HTTPException")
        raise
    except Exception as exc:
        session.rollback()
        existing = session.get(KnowledgeDocument, document_id)
        if existing is not None:
            _save_status(session, existing, status_value="failed", error="Unable to store or schedule document")
        logger.exception("Knowledge document upload failed for document_id=%s", document_id)
        trace.log_event("document.upload_failed", document_id=document_id, error_type=type(exc).__name__)
        raise HTTPException(status_code=502, detail="Unable to store document in object storage") from exc
    finally:
        session.close()
        Path(temp_path).unlink(missing_ok=True)
        await file.close()


@router.get("/{document_id}")
def get_knowledge_document_status(document_id: str):
    session = SessionLocal()
    try:
        document = session.get(KnowledgeDocument, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Knowledge document not found")
        return {
            "document_id": document.id,
            "filename": document.original_filename,
            "source_type": document.source_type,
            "version_number": document.version_number,
            "status": document.status,
            "file_size": document.file_size,
            "chunk_count": document.chunk_count,
            "retry_count": document.retry_count,
            "error": document.error_message,
            "created_at": document.created_at,
            "updated_at": document.updated_at,
            "completed_at": document.completed_at,
            "created_at_wib": to_wib_iso(document.created_at),
            "updated_at_wib": to_wib_iso(document.updated_at),
            "completed_at_wib": to_wib_iso(document.completed_at),
            "ingested_at_wib": to_wib_iso(document.completed_at),
        }
    finally:
        session.close()


@router.get("/{document_id}/chunks")
def get_knowledge_document_chunks(document_id: str):
    session = SessionLocal()
    try:
        document = session.get(KnowledgeDocument, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Knowledge document not found")

        rows = session.execute(
            text(
                """SELECT e.cmetadata, LEFT(e.document, 240)
                   FROM langchain_pg_embedding e
                   JOIN langchain_pg_collection c ON c.uuid = e.collection_id
                   WHERE c.name = :collection_name
                     AND e.cmetadata ->> 'document_id' = :document_id
                   ORDER BY (e.cmetadata ->> 'faq')::int ASC"""
            ),
            {
                "collection_name": collection_name_for(document.source_type),
                "document_id": document_id,
            },
        ).fetchall()

        chunks = []
        for metadata, preview in rows:
            metadata = metadata or {}
            chunks.append(
                {
                    "chunk": int(metadata.get("faq") or 0),
                    "document_id": metadata.get("document_id"),
                    "document_version": metadata.get("document_version"),
                    "source": metadata.get("source_file") or metadata.get("doc_name"),
                    "ingested_at_wib": metadata.get("ingested_at_wib"),
                    "chunk_hash": metadata.get("chunk_hash"),
                    "preview": str(preview or ""),
                }
            )
        return {
            "document_id": document_id,
            "source_type": document.source_type,
            "version_number": document.version_number,
            "status": document.status,
            "chunk_count": len(chunks),
            "chunks": chunks,
        }
    finally:
        session.close()


@router.post("/{document_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_knowledge_document(document_id: str):
    session = SessionLocal()
    try:
        document = session.get(KnowledgeDocument, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Knowledge document not found")
        if document.status not in {"failed", "uploaded"}:
            raise HTTPException(
                status_code=409,
                detail=f"Only failed or uploaded documents can be retried (current status: {document.status})",
            )

        document.status = "queued"
        document.error_message = None
        document.updated_at = datetime.utcnow()
        session.commit()
        try:
            task = ingest_uploaded_document.apply_async(args=[document_id])
        except CeleryError as exc:
            document.status = "failed"
            document.error_message = "Unable to enqueue document ingestion"
            document.updated_at = datetime.utcnow()
            session.commit()
            raise HTTPException(status_code=503, detail="Document ingestion queue is unavailable") from exc

        session.query(KnowledgeDocument).filter_by(id=document_id).update(
            {"celery_task_id": task.id, "updated_at": datetime.utcnow()},
            synchronize_session=False,
        )
        session.commit()
        session.refresh(document)
        return {
            "document_id": document.id,
            "task_id": task.id,
            "source_type": document.source_type,
            "version_number": document.version_number,
            "status": document.status,
        }
    finally:
        session.close()
