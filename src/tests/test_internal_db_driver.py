import importlib
import os
import sys
from urllib.parse import quote_plus
import pytest
from sqlalchemy import create_engine
from src.databases.internal.config import _normalize_postgres_uri


def test_internal_config_default_driver_is_psycopg3(monkeypatch):
    """Verify that default PostgreSQL URL explicitly uses postgresql+psycopg and loads psycopg3."""
    monkeypatch.delenv("INTERNAL_DB_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URI", raising=False)
    monkeypatch.delenv("INTERNAL_PORT", raising=False)
    monkeypatch.setenv("INTERNAL_HOST", "127.0.0.1")
    monkeypatch.setenv("INTERNAL_USER", "test_user")
    monkeypatch.setenv("INTERNAL_PASSWORD", "test_pass")
    monkeypatch.setenv("INTERNAL_DATABASE", "test_db")

    # Reload config module to evaluate with clean environment
    import src.databases.internal.config as cfg
    importlib.reload(cfg)

    assert cfg.INTERNAL_DB_URL.startswith("postgresql+psycopg://")
    assert "psycopg2" not in cfg.INTERNAL_DB_URL
    assert cfg.INTERNAL_PORT == "5433"
    assert ":5433/" in cfg.INTERNAL_DB_URL
    assert cfg.engine.dialect.name == "postgresql"
    assert cfg.engine.dialect.driver == "psycopg"
    assert cfg.engine.dialect.dbapi.__name__ == "psycopg"


def test_uri_normalization_and_sqlite_preservation():
    """Verify generic PostgreSQL URIs normalize to postgresql+psycopg and SQLite is preserved."""
    assert (
        _normalize_postgres_uri("postgresql://user:pass@localhost:5432/mydb")
        == "postgresql+psycopg://user:pass@localhost:5432/mydb"
    )
    assert (
        _normalize_postgres_uri("postgres://user:pass@localhost:5432/mydb")
        == "postgresql+psycopg://user:pass@localhost:5432/mydb"
    )
    assert (
        _normalize_postgres_uri("postgresql+psycopg://user:pass@localhost:5432/mydb")
        == "postgresql+psycopg://user:pass@localhost:5432/mydb"
    )
    assert _normalize_postgres_uri("sqlite:///:memory:") == "sqlite:///:memory:"


def test_url_override_via_env(monkeypatch):
    """Verify explicit alternative URL overrides (generic postgresql and sqlite) via env."""
    import src.databases.internal.config as cfg

    # 1. SQLite override preserved
    monkeypatch.setenv("INTERNAL_DB_URL", "sqlite:///:memory:")
    importlib.reload(cfg)
    assert cfg.INTERNAL_DB_URL == "sqlite:///:memory:"
    assert cfg.engine.dialect.name == "sqlite"

    # 2. Generic postgresql override normalized
    monkeypatch.setenv("INTERNAL_DB_URL", "postgresql://mock_user:mock_pass@127.0.0.1:5433/mock_db")
    importlib.reload(cfg)
    assert cfg.INTERNAL_DB_URL.startswith("postgresql+psycopg://")
    assert cfg.engine.dialect.driver == "psycopg"


def test_password_special_character_escaping(monkeypatch):
    """Verify special characters in credentials are escaped safely without corruption."""
    special_password = "p@ss:w/ord?#&=![]+^"
    monkeypatch.delenv("INTERNAL_DB_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URI", raising=False)
    monkeypatch.setenv("INTERNAL_HOST", "127.0.0.1")
    monkeypatch.setenv("INTERNAL_PORT", "5433")
    monkeypatch.setenv("INTERNAL_USER", "sync_user")
    monkeypatch.setenv("INTERNAL_PASSWORD", special_password)
    monkeypatch.setenv("INTERNAL_DATABASE", "sync_db")

    import src.databases.internal.config as cfg
    importlib.reload(cfg)

    assert cfg.engine.url.password == special_password
    assert cfg.engine.dialect.name == "postgresql"
    assert cfg.engine.dialect.driver == "psycopg"
