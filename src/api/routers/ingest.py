import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from pathlib import Path

from src.knowledge.ingestor import Ingestor
from src.semantic_cache import SemanticCache

router = APIRouter(prefix="/api/v1/ingest", tags=["ingestion"])


class IngestFileRequest(BaseModel):
    file_path: str = Field(..., description="Absolute or relative path to the markdown document to ingest")


class IngestTextRequest(BaseModel):
    content: str = Field(..., min_length=5, description="Markdown content to ingest")
    doc_name: Optional[str] = Field(default="document.md", description="Document identifier name")


@router.post("/file")
async def ingest_file_endpoint(req: IngestFileRequest):
    # Reads any path on the server, and the API has no authentication yet: off unless a
    # deployment turns it on. Uploads go through /api/v1/knowledge/documents instead.
    if os.getenv("KNOWLEDGE_INGEST_FILE_ENABLED", "false").lower() not in ("true", "1", "yes"):
        raise HTTPException(
            status_code=403,
            detail="Ingest from a server file path is disabled; upload through /api/v1/knowledge/documents.",
        )
    try:
        path = Path(req.file_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"File not found: {req.file_path}")

        ingestor = Ingestor()
        result = ingestor.ingest_file(path)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/text")
async def ingest_text_endpoint(req: IngestTextRequest):
    try:
        ingestor = Ingestor()
        result = ingestor.ingest_text(req.content, req.doc_name)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/clear-cache")
async def clear_cache_endpoint():
    try:
        cache = SemanticCache()
        cleared_items = cache.clear()
        return {
            "status": "success",
            "message": "Semantic cache cleared successfully",
            "cleared_items": cleared_items,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
