from typing import Optional, List, Any
from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Pesan pertanyaan dari pengguna.")
    conversation_id: str = Field(..., min_length=1, description="ID unik sesi percakapan (UUID).")
    user_id: str = Field(default="user_default", min_length=1, description="ID pengguna yang login.")
    enable_pii: bool = Field(default=True, description="Sensor otomatis untuk NIK dan data sensitif.")
    model_name: Optional[str] = Field(default=None, description="Override nama model LLM.")
    base_url: Optional[str] = Field(default=None, description="Override base URL API LLM.")

class ConversationItem(BaseModel):
    id: str
    user_id: str
    title: str
    created_at: Any
    updated_at: Any

class MessageItem(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    created_at: Any

class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    postgres_db: str
    analytics_db: str
    model: str
