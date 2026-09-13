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


def test_api_key_auth_when_configured(client, monkeypatch):
    """评审 P0-4:Settings.api_key 非空即启用鉴权,错/缺 X-API-Key 一律 401。"""
    from app.config import get_settings

    monkeypatch.setenv("API_KEY", "secret")
    get_settings.cache_clear()
    try:
        r = client.post("/ask", json={"question": "多少客户"})
        assert r.status_code == 401
        r = client.post("/ask", json={"question": "多少客户"}, headers={"X-API-Key": "wrong"})
        assert r.status_code == 401
        r = client.post("/ask", json={"question": "多少客户"}, headers={"X-API-Key": "secret"})
        assert r.status_code == 200 and r.json()["summary"] == "桩结论"
    finally:
        monkeypatch.delenv("API_KEY")
        get_settings.cache_clear()


def test_unexpected_exception_degrades_not_500(client, monkeypatch):
    """评审复评 P1-4:未预期异常不抛 500,对外只给通用文案(不泄漏异常类名),堆栈进服务端日志。"""
    def boom(question: str):
        raise RuntimeError("意外")

    monkeypatch.setattr(api, "get_service", lambda: type("S", (), {"ask": staticmethod(boom)})())
    body = client.post("/ask", json={"question": "多少客户"}).json()
    assert body["error"] == "服务内部错误,请稍后重试。"
    assert "RuntimeError" not in body["error"] and "意外" not in body["error"]


def test_request_id_header_and_rate_limit(client, monkeypatch):
    """复评 P1-3:响应带 X-Request-Id;rate_limit_per_min 非 0 时按 IP 固定窗口 429。"""
    from app.config import get_settings

    r = client.get("/health")
    assert len(r.headers.get("x-request-id", "")) == 8  # 未启用限流时也带 request id

    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "2")
    get_settings.cache_clear()
    try:
        assert client.post("/ask", json={"question": "多少客户"}).status_code == 200
        assert client.post("/ask", json={"question": "多少客户"}).status_code == 200
        r = client.post("/ask", json={"question": "多少客户"})
        assert r.status_code == 429 and r.json()["detail"].startswith("请求过于频繁")
    finally:
        monkeypatch.delenv("RATE_LIMIT_PER_MIN")
        get_settings.cache_clear()
        api._RATE_STATE.clear()
