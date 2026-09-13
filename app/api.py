"""FastAPI 接口:POST /ask(中文问题 → 结构化表格 + 结论 + 轨迹)。

生产化最小保护(评审 P0-4):
- 可选 API Key 鉴权:Settings.api_key 非空即启用,请求须带 X-API-Key 头(内网演示默认关闭);
- 异常兜底:service 未预期的异常不抛 500,降级为结构化 error 响应(与 agent 的优雅降级同口径);
- 连接回收在 service 层完成(每请求一连接,finally 关闭)。
限流/异步队列/Prometheus 指标属部署层能力,见 PROGRESS 路线图,不在 v0.1 范围。
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, Header, HTTPException

from .config import get_settings
from .schemas import AskRequest, AskResponse
from .service import get_service

app = FastAPI(title="chatbi", version="0.1.0")


def _require_key(x_api_key: str | None = Header(default=None)) -> None:
    key = get_settings().api_key
    if key and x_api_key != key:
        raise HTTPException(status_code=401, detail="缺少或错误的 X-API-Key 请求头")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse, dependencies=[Depends(_require_key)])
def ask(req: AskRequest) -> AskResponse:
    try:
        return get_service().ask(req.question)
    except Exception as e:  # noqa: BLE001 —— 兜底:不让内部异常变成 500 裸响应
        return AskResponse(question=req.question, error=f"内部错误:{type(e).__name__}(已兜底降级)")
