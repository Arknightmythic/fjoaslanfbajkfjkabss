from fastapi import APIRouter, Request, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional
import asyncio

from src.handler import ChatbotHandler, TitleGenerator
from src.databases import get_db

router = APIRouter(tags=["chat"])
chatbot_handler = ChatbotHandler()


class ChatRequest(BaseModel):
    user_id: str
    thread_id: str
    question: str
    connection_id: str = Field(..., min_length=1, description="Database connection ID is strictly required")
    enable_pii: Optional[bool] = Field(default=True, description="Enable PII detection and redaction in the response")

@router.post("/chat")
async def chat_endpoint(req: ChatRequest, request: Request):
    async def event_generator():
        try:
            async for chunk in chatbot_handler.stream(
                user_id=req.user_id,
                conversation_id=req.thread_id,
                question=req.question,
                connection_id=req.connection_id,
                enable_pii=req.enable_pii
            ):
                if await request.is_disconnected():
                    break
                yield chunk
        except asyncio.CancelledError:
            pass

    return StreamingResponse(event_generator(), media_type="text/event-stream")

