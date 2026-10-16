import os
from functools import lru_cache
from dotenv import load_dotenv

from src.databases.connectors.base import DatabaseConnector
from src.databases.connectors.mysql import MySQLConnector

load_dotenv()


connector = MySQLConnector(
    host=os.getenv("MYSQL_HOST", "127.0.0.1"),
    port=int(os.getenv("MYSQL_PORT", "3306")),
    database=os.getenv("MYSQL_DATABASE", "synchrono"),
    username=os.getenv("MYSQL_USER", "synchrono_readonly"),
    password=os.getenv("MYSQL_PASSWORD", ""),
)

def get_active_connector() -> DatabaseConnector:
    return connector
