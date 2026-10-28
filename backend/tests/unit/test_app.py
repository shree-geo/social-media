import logging

import pytest
import structlog
from fastapi.testclient import TestClient

from app.core.ids import new_id
from app.core.logging import redact_secrets
from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_live_health(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_request_id_is_generated_and_returned(client: TestClient) -> None:
    response = client.get("/health/live")
    assert len(response.headers["x-request-id"]) >= 8


def test_valid_incoming_request_id_is_kept(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "abc12345-req"})
    assert response.headers["x-request-id"] == "abc12345-req"


def test_malformed_incoming_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "bad id<script>"})
    assert response.headers["x-request-id"] != "bad id<script>"


def test_security_headers_present(client: TestClient) -> None:
    headers = client.get("/health/live").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in headers["content-security-policy"]


def test_unknown_route_returns_problem_details(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "not_found"
    assert body["request_id"] == response.headers["x-request-id"]


def test_redaction_hides_secrets_but_keeps_ordinary_fields() -> None:
    event = {
        "event": "x",
        "access_token": "EAAG...",
        "password": "hunter2",
        "code": "oauth-code",
        "status_code": 200,
        "payload": {"page_token": "abc", "name": "Ram"},
    }
    out = redact_secrets(None, "info", dict(event))
    assert out["access_token"] == out["password"] == out["code"] == "[REDACTED]"
    assert out["status_code"] == 200
    assert out["payload"] == {"page_token": "[REDACTED]", "name": "Ram"}


def test_new_id_is_uuid7_and_time_ordered() -> None:
    first, second = new_id(), new_id()
    assert first.version == 7
    assert first < second


def test_structlog_configured() -> None:
    assert structlog.is_configured()
    assert logging.getLogger().handlers
