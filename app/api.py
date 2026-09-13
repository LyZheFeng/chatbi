"""FastAPI 接口:POST /ask(中文问题 → 结构化表格 + 结论 + 轨迹)。"""

from __future__ import annotations

from fastapi import FastAPI

from .schemas import AskRequest, AskResponse
from .service import get_service

app = FastAPI(title="chatbi", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    return get_service().ask(req.question)
