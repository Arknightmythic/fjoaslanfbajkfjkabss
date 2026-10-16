from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from src.api.routers import chat, ui

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

if ui.STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(ui.STATIC_DIR)), name="static")
    app.include_router(ui.router)

@app.get("/")
async def health_check():
    return {"status": "ok", "message": "Synchrono Chatbot API is running."}
