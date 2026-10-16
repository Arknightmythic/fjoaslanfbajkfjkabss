from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import FileResponse

STATIC_DIR = Path("static")

router = APIRouter(tags=["ui"])

@router.get("/", include_in_schema=False)
@router.get("/test-ui", include_in_schema=False)
async def serve_test_ui():
    return FileResponse(str(STATIC_DIR / "index.html"))

@router.get("/batch-synchronization/investigate", include_in_schema=False)
async def serve_investigate():
    return FileResponse(str(STATIC_DIR / "investigate.html"))

@router.get("/batch-synchronization/preview", include_in_schema=False)
async def serve_preview():
    return FileResponse(str(STATIC_DIR / "preview.html"))
