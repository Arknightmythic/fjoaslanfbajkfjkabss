from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os

load_dotenv()

INTERNAL_HOST: str = os.getenv("INTERNAL_HOST", "127.0.0.1")
INTERNAL_PORT: str = os.getenv("INTERNAL_PORT", "5433")
INTERNAL_USER: str = os.getenv("INTERNAL_USER", "")
INTERNAL_PASSWORD: str = os.getenv("INTERNAL_PASSWORD", "")
INTERNAL_DATABASE: str = os.getenv("INTERNAL_DATABASE", "")

INTERNAL_DB_URL: str = URL.create(
    "postgresql+psycopg",
    username=INTERNAL_USER,
    password=INTERNAL_PASSWORD,
    host=INTERNAL_HOST,
    port=int(INTERNAL_PORT),
    database=INTERNAL_DATABASE,
).render_as_string(hide_password=False)

engine = create_engine(INTERNAL_DB_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
