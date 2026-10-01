import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

load_dotenv()

class PostgresConversationDB:
    def __init__(self, uri: Optional[str] = None):
        self.uri = uri or os.getenv(
            "POSTGRES_URI", 
            "postgresql://synchrono:synchrono123@localhost:5433/synchrono_chatbot"
        )
        self.engine: Engine = self._init_engine()
        self._ensure_tables()

    def _init_engine(self) -> Engine:
        """Initialize PostgreSQL engine with connection pooling and graceful SQLite fallback."""
        try:
            uri = self.uri
            if uri.startswith("postgresql://") and "+psycopg" not in uri:
                uri = uri.replace("postgresql://", "postgresql+psycopg://")
            engine = create_engine(
                uri,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,
                pool_recycle=1800,
            )
            # Test immediate connectivity
            with engine.connect() as conn:
                conn.execute(text("SELECT 1;"))
            print(f"[DB] Terhubung ke PostgreSQL conversation database: {self.uri.split('@')[-1]}")
            return engine
        except Exception as e:
            print(f"[DB WARNING] Gagal terhubung ke PostgreSQL ({e}). Menggunakan SQLite lokal sebagai fallback sementara.")
            os.makedirs("data", exist_ok=True)
            fallback_uri = "sqlite:///data/conversations_fallback.db"
            return create_engine(fallback_uri)

    def _ensure_tables(self) -> None:
        """Create conversations and messages tables if they do not exist."""
        try:
            with self.engine.begin() as conn:
                is_sqlite = "sqlite" in str(self.engine.url)
                timestamp_type = "DATETIME" if is_sqlite else "TIMESTAMPTZ"

                conn.execute(text(f"""
                    CREATE TABLE IF NOT EXISTS conversations (
                        id VARCHAR(64) PRIMARY KEY,
                        user_id VARCHAR(64) NOT NULL,
                        title TEXT NOT NULL,
                        created_at {timestamp_type} NOT NULL,
                        updated_at {timestamp_type} NOT NULL
                    );
                """))
                conn.execute(text(f"""
                    CREATE TABLE IF NOT EXISTS messages (
                        id VARCHAR(64) PRIMARY KEY,
                        conversation_id VARCHAR(64) NOT NULL,
                        role VARCHAR(16) NOT NULL,
                        content TEXT NOT NULL,
                        created_at {timestamp_type} NOT NULL,
                        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                    );
                """))
                if not is_sqlite:
                    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id);"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);"))
        except Exception as e:
            print(f"[DB ERROR] Error ensuring conversation tables: {e}")

    def conversation_exists(self, conversation_id: str) -> bool:
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT 1 FROM conversations WHERE id = :id LIMIT 1"),
                    {"id": conversation_id}
                ).fetchone()
                return result is not None
        except Exception:
            return False

    def insert_conversation(self, conversation_id: str, title: str, user_id: str) -> None:
        now = datetime.now(timezone.utc)
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO conversations (id, user_id, title, created_at, updated_at)
                        VALUES (:id, :user_id, :title, :created_at, :updated_at)
                    """),
                    {
                        "id": conversation_id,
                        "user_id": user_id,
                        "title": title,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
        except Exception as e:
            print(f"[DB ERROR] Insert conversation failed: {e}")

    def update_conversation_timestamp(self, conversation_id: str) -> None:
        now = datetime.now(timezone.utc)
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text("UPDATE conversations SET updated_at = :updated_at WHERE id = :id"),
                    {"id": conversation_id, "updated_at": now}
                )
        except Exception as e:
            print(f"[DB ERROR] Update conversation timestamp failed: {e}")

    def insert_message(self, conversation_id: str, content: str, role: str) -> None:
        msg_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO messages (id, conversation_id, role, content, created_at)
                        VALUES (:id, :conversation_id, :role, :content, :created_at)
                    """),
                    {
                        "id": msg_id,
                        "conversation_id": conversation_id,
                        "role": role,
                        "content": content,
                        "created_at": now,
                    }
                )
        except Exception as e:
            print(f"[DB ERROR] Insert message failed: {e}")

    def get_conversations(self, user_id: str) -> List[Dict[str, Any]]:
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT id, user_id, title, created_at, updated_at
                        FROM conversations
                        WHERE user_id = :user_id
                        ORDER BY updated_at DESC
                    """),
                    {"user_id": user_id}
                ).mappings().fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            print(f"[DB ERROR] Get conversations failed: {e}")
            return []

    def get_messages(self, conversation_id: str) -> List[Dict[str, Any]]:
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT id, conversation_id, role, content, created_at
                        FROM messages
                        WHERE conversation_id = :conversation_id
                        ORDER BY created_at ASC
                    """),
                    {"conversation_id": conversation_id}
                ).mappings().fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            print(f"[DB ERROR] Get messages failed: {e}")
            return []

    def delete_conversation(self, conversation_id: str) -> bool:
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM messages WHERE conversation_id = :id"),
                    {"id": conversation_id}
                )
                conn.execute(
                    text("DELETE FROM conversations WHERE id = :id"),
                    {"id": conversation_id}
                )
            return True
        except Exception as e:
            print(f"[DB ERROR] Delete conversation failed: {e}")
            return False

# Global instance
conv_db = PostgresConversationDB()
