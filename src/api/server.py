from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from loguru import logger

from src.api.routers import chat, ui, ingest, documents

load_dotenv()

app = FastAPI(
    title="Synchrono Chatbot API",
    version="1.0.0",
    description="Enterprise Data Analyst Chatbot API for Synchrono Platform",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(ingest.router)
app.include_router(documents.router)

if ui.STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(ui.STATIC_DIR)), name="static")
    app.include_router(ui.router)


@app.get("/api/v1/health")
async def health_check():
    return {"status": "healthy", "service": "synchrono-chatbot"}

