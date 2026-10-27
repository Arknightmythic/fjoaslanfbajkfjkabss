import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def isolated_app():
    """Lazily load app after conftest.py test DB isolation is initialized."""
    from src.api.server import app
    return app


def test_app_identity():
    """Verify main.py exports identical app instance from src.api.server."""
    from src.api.server import app as server_app
    from main import app as main_app

    assert server_app is main_app


def test_representative_endpoints(isolated_app):
    """Verify OpenAPI docs, health API, and static UI routes respond."""
    client = TestClient(isolated_app)

    # Docs endpoint
    docs_res = client.get("/docs")
    assert docs_res.status_code == 200

    # API health endpoint
    health_res = client.get("/api/v1/health")
    assert health_res.status_code == 200
    data = health_res.json()
    assert data.get("status") == "healthy"
    assert data.get("service") == "synchrono-chatbot"
    assert data == {"status": "healthy", "service": "synchrono-chatbot"}

    # Static web UI endpoints
    ui_res = client.get("/")
    assert ui_res.status_code == 200
    assert "text/html" in ui_res.headers.get("content-type", "")

    # Static asset endpoint
    static_asset_res = client.get("/static/style.css")
    assert static_asset_res.status_code == 200


def test_static_path_cwd_independence(isolated_app, tmp_path, monkeypatch):
    """Verify static root resolution does not depend on current working directory."""
    monkeypatch.chdir(tmp_path)
    client = TestClient(isolated_app)

    # Static UI and asset should still serve properly despite different cwd
    root_res = client.get("/")
    assert root_res.status_code == 200

    asset_res = client.get("/static/style.css")
    assert asset_res.status_code == 200
