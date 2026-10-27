import importlib.util
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.databases.internal.config import get_db

CONFIG_PATH = Path(__file__).resolve().parents[1] / "databases" / "internal" / "config.py"


def _load_config_module(name: str):
    spec = importlib.util.spec_from_file_location(name, CONFIG_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_config_builds_psycopg_url_from_env(monkeypatch):
    special_password = "p@ss:w/ord?#&=![]+^"
    monkeypatch.setenv("INTERNAL_HOST", "127.0.0.1")
    monkeypatch.setenv("INTERNAL_PORT", "5433")
    monkeypatch.setenv("INTERNAL_USER", "sync_user")
    monkeypatch.setenv("INTERNAL_PASSWORD", special_password)
    monkeypatch.setenv("INTERNAL_DATABASE", "sync_db")

    config = _load_config_module("src.databases.internal.config_env_test")
    try:
        assert config.INTERNAL_DB_URL.startswith("postgresql+psycopg://")
        assert "psycopg2" not in config.INTERNAL_DB_URL
        assert config.engine.url.username == "sync_user"
        assert config.engine.url.password == special_password
        assert config.engine.url.host == "127.0.0.1"
        assert config.engine.url.port == 5433
        assert config.engine.url.database == "sync_db"
        assert config.engine.dialect.name == "postgresql"
        assert config.engine.dialect.driver == "psycopg"
    finally:
        config.engine.dispose()


def test_config_import_does_not_open_network_connection(monkeypatch):
    monkeypatch.setenv("INTERNAL_HOST", "127.0.0.1")
    monkeypatch.setenv("INTERNAL_PORT", "5433")
    monkeypatch.setenv("INTERNAL_USER", "sync_user")
    monkeypatch.setenv("INTERNAL_PASSWORD", "secret")
    monkeypatch.setenv("INTERNAL_DATABASE", "sync_db")

    with patch("socket.socket.connect") as connect:
        config = _load_config_module("src.databases.internal.config_import_test")
        try:
            assert connect.called is False
        finally:
            config.engine.dispose()


def test_get_db_closes_session_on_normal_and_error_exit(monkeypatch):
    engine = create_engine("sqlite://")
    test_session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr("src.databases.internal.config.SessionLocal", test_session_factory)

    with patch.object(Session, "close", autospec=True) as close:
        generator = get_db()
        session = next(generator)
        assert isinstance(session, Session)
        assert close.called is False
        try:
            next(generator)
        except StopIteration:
            pass
        assert close.called

    with patch.object(Session, "close", autospec=True) as close:
        generator = get_db()
        session = next(generator)
        assert isinstance(session, Session)
        try:
            generator.throw(RuntimeError("client disconnected"))
        except RuntimeError:
            pass
        assert close.called

    engine.dispose()
