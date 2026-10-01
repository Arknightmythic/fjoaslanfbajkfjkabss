import os
import time
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from api.schemas import ChatRequest, ConversationItem, MessageItem, HealthResponse
from chatbot.handler import ChatbotHandler
from chatbot.database import conv_db, query_engine

router = APIRouter(prefix="/api/v1", tags=["Chatbot"])

_DEFAULT_HANDLER: Optional[ChatbotHandler] = None

def get_chatbot_handler(model_name: Optional[str] = None, base_url: Optional[str] = None) -> ChatbotHandler:
    global _DEFAULT_HANDLER
    if model_name or base_url:
        return ChatbotHandler(model_name=model_name, base_url=base_url)
    if _DEFAULT_HANDLER is None:
        _DEFAULT_HANDLER = ChatbotHandler()
    return _DEFAULT_HANDLER

@router.post(
    "/chat", 
    summary="Kirim pesan dan stream respons chatbot (SSE)",
    description="Mengirim pertanyaan ke agen data analyst Synchrono dengan respons streaming Server-Sent Events (SSE)."
)
async def chat_stream(request: ChatRequest):
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Pertanyaan tidak boleh kosong.")

    try:
        agent = get_chatbot_handler(
            model_name=request.model_name,
            base_url=request.base_url,
        )
        return StreamingResponse(
            agent.stream(
                user_id=request.user_id,
                conversation_id=request.conversation_id,
                question=request.query,
                enable_pii=request.enable_pii,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal memproses pesan: {e}")

@router.get(
    "/conversations", 
    response_model=List[ConversationItem],
    summary="Ambil daftar percakapan pengguna",
    description="Mengambil seluruh riwayat sesi percakapan dari database PostgreSQL berdasarkan user_id."
)
async def list_conversations(user_id: str = Query(..., description="ID Pengguna")):
    try:
        return conv_db.get_conversations(user_id=user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get(
    "/conversations/{conversation_id}", 
    response_model=List[MessageItem],
    summary="Ambil riwayat pesan dalam sesi percakapan",
    description="Mengambil seluruh bubble chat (human & ai) untuk percakapan tertentu yang tersimpan di PostgreSQL."
)
async def get_messages(conversation_id: str):
    try:
        messages = conv_db.get_messages(conversation_id=conversation_id)
        return messages
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete(
    "/conversations/{conversation_id}", 
    summary="Hapus riwayat sesi percakapan",
    description="Menghapus sesi percakapan dan seluruh pesannya dari database PostgreSQL."
)
async def delete_conversation(conversation_id: str):
    success = conv_db.delete_conversation(conversation_id=conversation_id)
    if not success:
        raise HTTPException(status_code=404, detail="Sesi percakapan tidak ditemukan atau gagal dihapus.")
    return {"status": "success", "message": f"Sesi {conversation_id} berhasil dihapus."}

@router.get(
    "/health", 
    response_model=HealthResponse,
    summary="Healthcheck Service & Status Database",
    description="Memeriksa status operasional service, koneksi PostgreSQL, dan database analitik."
)
async def health_check():
    pg_url = str(conv_db.engine.url)
    analytics_url = str(query_engine.engine.url) if query_engine.engine else "Not connected"
    
    return HealthResponse(
        status="healthy",
        service="synchrono-chatbot",
        version="1.0.0",
        postgres_db=pg_url.split("@")[-1] if "@" in pg_url else pg_url,
        analytics_db=analytics_url.split("@")[-1] if "@" in analytics_url else analytics_url,
        model=os.getenv("CHATBOT_MODEL", "gemma4:31b-cloud")
    )

@router.get(
    "/investigate/{file_id}",
    summary="Ambil data investigasi file",
    description="Mengambil detail file dan daftar antrean manual review untuk file tertentu."
)
async def get_investigation_data(file_id: str):
    if not query_engine or not query_engine.engine:
        raise HTTPException(status_code=503, detail="Database analitik tidak terhubung.")
    
    try:
        from sqlalchemy import text
        with query_engine.engine.connect() as conn:
            f_rows = conn.execute(
                text("SELECT * FROM uploaded_files WHERE file_id = :file_id"),
                {"file_id": file_id}
            ).mappings().fetchall()
            file_info = dict(f_rows[0]) if f_rows else None
            
            m_rows = conn.execute(
                text("SELECT * FROM manual_matches WHERE file_id = :file_id ORDER BY id_incoming ASC"),
                {"file_id": file_id}
            ).mappings().fetchall()
            matches = [dict(r) for r in m_rows]
            
        return {
            "status": "success",
            "file": file_info,
            "manual_matches": matches
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
