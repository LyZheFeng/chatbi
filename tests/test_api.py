"""api.py:/health 与 /ask(替换 service 为桩,不打网络)。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import api
from app.schemas import AskResponse


@pytest.fixture()
def client(monkeypatch):
    def fake_ask(question: str) -> AskResponse:
        return AskResponse(
            question=question,
            summary="桩结论",
            sql="SELECT 1",
            columns=["n"],
            rows=[[1]],
            row_count=1,
            latency_ms=1,
        )

    monkeypatch.setattr(api, "get_service", lambda: type("S", (), {"ask": staticmethod(fake_ask)})())
    return TestClient(api.app)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_ask_happy(client):
    body = client.post("/ask", json={"question": "多少客户"}).json()
    assert body["summary"] == "桩结论"
    assert body["rows"] == [[1]] and body["sql"] == "SELECT 1"
    assert body["error"] is None


def test_ask_rejects_too_short_question(client):
    resp = client.post("/ask", json={"question": "多"})
    assert resp.status_code == 422
