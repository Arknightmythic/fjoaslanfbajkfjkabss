import os
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

from api.routes import router as api_router
from chatbot.database import conv_db, query_engine

load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("=" * 60)
    print("[START] Synchrono AI Chatbot Service Starting...")
    print(f"[*] Model Configured: {os.getenv('OPENAI_MODEL_NAME') or os.getenv('CHATBOT_MODEL', 'gemma4:31b-cloud')}")
    print(f"[*] PostgreSQL DB: {conv_db.engine.url}")
    print(f"[*] Analytics DB: {query_engine.engine.url if query_engine.engine else 'None'}")
    print("=" * 60)
    yield
    print("[STOP] Synchrono AI Chatbot Service Stopping...")

app = FastAPI(
    title="Synchrono Chatbot API",
    version="1.0.0",
    description="Enterprise Data Analyst Chatbot API for Synchrono Platform",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS for Frontend Website integration
cors_origins_raw = os.getenv("CORS_ORIGINS", '["*"]')
try:
    origins = json.loads(cors_origins_raw)
except Exception:
    origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Router
app.include_router(api_router)

# Mount Static Files for Testing Web UI
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    @app.get("/test-ui", include_in_schema=False)
    async def serve_test_ui():
        return FileResponse(os.path.join(static_dir, "index.html"))

    @app.get("/batch-synchronization/investigate", include_in_schema=False)
    async def serve_investigate():
        return FileResponse(os.path.join(static_dir, "investigate.html"))

    @app.get("/batch-synchronization/preview", include_in_schema=False)
    async def serve_preview():
        return FileResponse(os.path.join(static_dir, "preview.html"))

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run("main:app", host=host, port=port, reload=True)
