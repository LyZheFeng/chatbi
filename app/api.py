"""FastAPI 接口:POST /ask(中文问题 → 结构化表格 + 结论 + 轨迹)。

生产化最小保护(评审两轮后):
- 可选 API Key 鉴权:Settings.api_key 非空即启用,请求须带 X-API-Key 头(内网演示默认关闭);
- 观测最小集:每请求 X-Request-Id 响应头 + 结构化访问日志(方法/路径/状态/耗时);
- 可选限流:rate_limit_per_min 非 0 时按客户端 IP 固定窗口计数,超限 429(进程内,单 worker 有效);
- 异常兜底:对外只给通用错误文案,完整异常堆栈记服务端日志;LLM 繁忙(并发闸门超时)转 503。
限流分布式版/Prometheus 指标/异步任务队列属部署层,见 PROGRESS 路线图。
"""

from __future__ import annotations

import logging
import threading
import time
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from .config import get_settings
from .llm import LLMBusy
from .schemas import AskRequest, AskResponse
from .service import get_service

logger = logging.getLogger("chatbi.api")

app = FastAPI(title="chatbi", version="0.1.0")

# 限流状态:ip -> (窗口起点 epoch 秒, 计数)。进程内字典,单 worker 有效
_RATE_STATE: dict[str, tuple[int, int]] = {}
_RATE_LOCK = threading.Lock()
_RATE_MAX_ENTRIES = 10_000  # 字典规模上限,超过即惰性清扫过期窗口(防伪造来源撑爆内存)
_RATE_WINDOW_S = 60


def _require_key(x_api_key: str | None = Header(default=None)) -> None:
    key = get_settings().api_key
    if key and x_api_key != key:
        raise HTTPException(status_code=401, detail="缺少或错误的 X-API-Key 请求头")


@app.middleware("http")
async def _observe(request, call_next):
    """request id + 访问日志 + 可选按 IP 固定窗口限流(只限写路径 /ask)。"""
    rid = uuid.uuid4().hex[:8]
    t0 = time.perf_counter()

    limit = get_settings().rate_limit_per_min
    if limit and request.url.path == "/ask" and request.client:
        now = int(time.time())
        with _RATE_LOCK:
            if len(_RATE_STATE) >= _RATE_MAX_ENTRIES:  # 惰性清扫:过期窗口即伪 IP 遗留
                for ip in [ip for ip, (s, _) in _RATE_STATE.items() if now - s >= _RATE_WINDOW_S]:
                    _RATE_STATE.pop(ip, None)
            start, count = _RATE_STATE.get(request.client.host, (now, 0))
            if now - start >= _RATE_WINDOW_S:
                start, count = now, 0
            _RATE_STATE[request.client.host] = (start, count + 1)
            over = count + 1 > limit
        if over:
            logger.warning("rid=%s 429 rate-limited client=%s", rid, request.client.host)
            resp = JSONResponse(status_code=429, content={"detail": "请求过于频繁,请稍后重试"})
            resp.headers["X-Request-Id"] = rid
            return resp

    response = await call_next(request)
    logger.info("rid=%s %s %s -> %s %.0fms",
                rid, request.method, request.url.path, response.status_code,
                (time.perf_counter() - t0) * 1000)
    response.headers["X-Request-Id"] = rid
    return response


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse, dependencies=[Depends(_require_key)])
def ask(req: AskRequest) -> AskResponse:
    try:
        return get_service().ask(req.question)
    except LLMBusy as e:
        logger.warning("LLM 繁忙:%s", e)
        return AskResponse(question=req.question, error="LLM 当前繁忙,请稍后重试。")
    except Exception:  # noqa: BLE001 —— 兜底:对外通用文案,堆栈只进服务端日志
        logger.exception("ask 未预期异常")
        return AskResponse(question=req.question, error="服务内部错误,请稍后重试。")
