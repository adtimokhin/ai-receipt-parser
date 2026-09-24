"""Base smoke test (overlay-contract 7).

The app imports, liveness is 200, and readiness is 200 with every registered
check healthy. With no overlays selected the readiness check set is empty.
"""

from __future__ import annotations

from starlette.testclient import TestClient


def test_app_module_imports() -> None:
    from receipt_parser_backend.main import app

    assert app.title == "receipt-parser-backend"


def test_health_live(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_ready(client: TestClient) -> None:
    response = client.get("/health/ready")
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ready"
    assert all(check["healthy"] for check in body["checks"].values())


def test_root(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "receipt-parser-backend"


def test_correlation_id_header(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.headers.get("x-request-id")
