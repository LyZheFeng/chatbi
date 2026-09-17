"""流式链路:service.ask_stream 事件序(FakeLLM 驱动)+ /ask/stream SSE 编码(桩 service)。

口径与 rag-qa test_stream_api.py 对齐:事件序 sources*(累计 steps)→ delta*(结论分段)
→ done(权威终态);LLM 繁忙/未预期异常收拢为 error 事件;鉴权/限流/CORS 同样覆盖流式路径。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import api
from app.agent import ChatbiAgent
from app.schemas import AskResponse
from app.service import ChatbiService
from tests.test_agent import FakeLLM, _msg, _tc

MARKET_SQL = ("SELECT market, SUM(sales) AS total FROM order_items i "
              "JOIN orders o ON i.order_id=o.order_id JOIN customers c ON o.customer_id=c.customer_id "
              "JOIN geography g ON c.country=g.country AND c.region=g.region GROUP BY market")


def _frames(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        event, data = None, None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if event is not None:
            out.append((event, data))
    return out


# ---------- service.ask_stream(FakeLLM + mini 库,不打网络) ----------


def test_stream_happy_event_sequence(conn):
    llm = FakeLLM([
        _msg([_tc("get_schema")]),
        _msg([_tc("execute_sql", sql=MARKET_SQL)]),
        _msg([_tc("final_answer", summary="Europe 市场销售额约 1815 美元,居首。Asia Pacific 次之,约 750 美元。", sql="SELECT market, SUM(sales) FROM ... GROUP BY market")]),
    ])
    events = list(ChatbiService(lambda: ChatbiAgent(llm, conn)).ask_stream("各市场总销售额"))
    kinds = [e for e, _ in events]
    # 事件序:每个工具调用后一次 sources(累计),随后结论 delta*,最后 done 收尾
    assert kinds[:3] == ["sources", "sources", "sources"]
    assert kinds[-1] == "done"
    assert set(kinds[3:-1]) == {"delta"} and kinds.count("delta") >= 1
    # sources 是累计的:第 n 次事件带 n 步
    for n, (_, payload) in enumerate([e for e in events if e[0] == "sources"], start=1):
        assert len(payload["steps"]) == n
        assert payload["steps"][-1]["tool"] in {"get_schema", "execute_sql", "final_answer"}
    # delta 拼接 == done.summary(分段只是呈现节奏,内容不改)
    text = "".join(p["text"] for e, p in events if e == "delta")
    done = [p for e, p in events if e == "done"][0]
    assert text == done["summary"] == "Europe 市场销售额约 1815 美元,居首。Asia Pacific 次之,约 750 美元。"
    # done 是权威终态:图表/表格/SQL/轨迹/统计齐备
    assert done["chart_spec"] is not None and done["chart_reading"]
    assert done["columns"] == ["market", "total"] and done["row_count"] == 2
    assert done["sql"].startswith("SELECT market, SUM(sales) FROM ...")
    assert len(done["steps"]) == 3 and done["error"] is None
    assert done["stats"]["llm_tokens"] == 0  # FakeLLM 无 used_tokens,记 0


def test_stream_degrade_goes_done_not_transport_error(conn):
    """自愈关闭 + SQL 首错:优雅降级走 done(error 字段),不发 error 事件、无 delta。"""
    llm = FakeLLM([
        _msg([_tc("get_schema")]),
        _msg([_tc("execute_sql", sql="SELECT bad_col FROM order_items")]),
    ])
    agent = ChatbiAgent(llm, conn, self_heal=False)
    events = list(ChatbiService(lambda: agent).ask_stream("多少行明细"))
    kinds = [e for e, _ in events]
    assert kinds == ["sources", "sources", "done"]
    done = events[-1][1]
    assert "自愈已关闭" in done["error"] and done["chart_spec"] is None


def test_stream_same_steps_as_run(conn):
    """stream() 与 run() 共用同一循环:步骤/结论/SQL 完全一致,仅产出时机不同。"""
    script = [
        _msg([_tc("get_schema")]),
        _msg([_tc("execute_sql", sql=MARKET_SQL)]),
        _msg([_tc("final_answer", summary="Europe 居首。", sql="SELECT market, SUM(sales) FROM ... GROUP BY market")]),
    ]
    r_run = ChatbiAgent(FakeLLM(script), conn).run("各市场总销售额")
    streamed = [s for s in ChatbiAgent(FakeLLM(script), conn).stream("各市场总销售额")]
    assert [s.model_dump() for s in streamed] == [s.model_dump() for s in r_run.steps]
    assert r_run.summary == "Europe 居首。"


# ---------- /ask/stream(桩 service,只测 SSE 编码与接口保护) ----------

_STUB_DONE = {
    "question": "q", "summary": "桩结论。", "sql": "SELECT 1", "columns": ["n"],
    "rows": [[1]], "row_count": 1, "chart_spec": None, "chart_reading": "",
    "steps": [], "error": None, "latency_ms": 1, "stats": {},
}


@pytest.fixture()
def stream_client(monkeypatch):
    def fake_ask_stream(question: str):
        yield "sources", {"steps": [{"step": 1, "tool": "get_schema", "args": {}, "ok": True, "detail": "ok"}]}
        yield "delta", {"text": "桩结论。"}
        yield "done", dict(_STUB_DONE, question=question)

    monkeypatch.setattr(api, "get_service", lambda: type("S", (), {"ask_stream": staticmethod(fake_ask_stream)})())
    return TestClient(api.app)


def test_stream_sse_wire_format(stream_client):
    resp = stream_client.get("/ask/stream", params={"q": "多少客户"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    frames = _frames(resp.text)
    assert [e for e, _ in frames] == ["sources", "delta", "done"]
    assert frames[0][1]["steps"][0]["tool"] == "get_schema"
    assert frames[2][1]["summary"] == "桩结论。"


def test_stream_query_validation(stream_client):
    assert stream_client.get("/ask/stream", params={"q": "多"}).status_code == 422


def test_stream_llm_busy_yields_error_event(monkeypatch):
    from app.llm import LLMBusy

    def boom(question: str):
        raise LLMBusy("闸门超时")
        yield  # pragma: no cover —— 让它是生成器

    monkeypatch.setattr(api, "get_service", lambda: type("S", (), {"ask_stream": staticmethod(boom)})())
    frames = _frames(TestClient(api.app).get("/ask/stream", params={"q": "多少客户"}).text)
    assert frames == [("error", {"message": "LLM 当前繁忙,请稍后重试。"})]


def test_stream_unexpected_exception_degrades(monkeypatch):
    def boom(question: str):
        raise RuntimeError("意外")
        yield  # pragma: no cover

    monkeypatch.setattr(api, "get_service", lambda: type("S", (), {"ask_stream": staticmethod(boom)})())
    text = TestClient(api.app).get("/ask/stream", params={"q": "多少客户"}).text
    frames = _frames(text)
    assert frames[0][0] == "error"
    assert "RuntimeError" not in text and "意外" not in text  # 不泄漏异常类名/内部信息
    assert frames[0][1]["message"] == "服务内部错误,请稍后重试。"


def test_stream_api_key_auth_when_configured(stream_client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("API_KEY", "secret")
    get_settings.cache_clear()
    try:
        assert stream_client.get("/ask/stream", params={"q": "多少客户"}).status_code == 401
        ok = stream_client.get("/ask/stream", params={"q": "多少客户"}, headers={"X-API-Key": "secret"})
        assert ok.status_code == 200 and "event: done" in ok.text
    finally:
        monkeypatch.delenv("API_KEY")
        get_settings.cache_clear()


def test_stream_rate_limited(stream_client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "1")
    get_settings.cache_clear()
    try:
        assert stream_client.get("/ask/stream", params={"q": "多少客户"}).status_code == 200
        r = stream_client.get("/ask/stream", params={"q": "多少客户"})
        assert r.status_code == 429 and r.json()["detail"].startswith("请求过于频繁")
    finally:
        monkeypatch.delenv("RATE_LIMIT_PER_MIN")
        get_settings.cache_clear()
        api._RATE_STATE.clear()


def test_cors_allows_next_dev_origin(stream_client):
    for path, method in [("/ask/stream", "GET"), ("/ask", "POST")]:
        resp = stream_client.options(
            path,
            headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": method},
        )
        assert resp.status_code == 200
        assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"
