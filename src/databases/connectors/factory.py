import os
from functools import lru_cache
from dotenv import load_dotenv

from src.databases.connectors.base import DatabaseConnector
from src.databases.connectors.mysql import MySQLConnector

load_dotenv()


connector = MySQLConnector(
    host=os.getenv("DB_HOST", "127.0.0.1"),
    port=int(os.getenv("DB_PORT", "3306")),
    database=os.getenv("DB_NAME", "synchrono"),
    username=os.getenv("DB_USER", "synchrono_readonly"),
    password=os.getenv("DB_PASSWORD", ""),
)

def get_active_connector() -> DatabaseConnector:
    return connector
