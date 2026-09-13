"""全局配置:LLM 端点 + 数据库路径 + 循环参数。

非法配置在 Settings 实例化时即抛 ValidationError(启动即失败,不带病运行)。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), env_file_encoding="utf-8", extra="ignore")

    llm_base_url: str
    llm_api_key: str = "1234"
    llm_model: str
    llm_max_retries: int = 3  # openai SDK 内建重试次数(连接错误/429/5xx,指数退避)

    db_path: str = str(ROOT / "data" / "chatbi.db")
    max_tool_steps: int = 8   # agent 循环上限(所有工具调用总次数)
    sql_row_cap: int = 200    # 单次查询最多返回给模型/前端的行数
    auto_limit: int = 100     # SQL 未写 LIMIT 时自动补的默认上限

    self_heal: bool = True        # 自愈循环开关(错误回传重试 + 结果反思);off = 首错即降级
    max_sql_retries: int = 3      # execute_sql 连续失败上限,超过即优雅降级
    sql_timeout_s: float = 5.0    # 单条 SQL 执行超时(progress_handler 掐断算力攻击/失控查询)
    api_key: str = ""             # 非空即启用 API 鉴权(请求须带 X-API-Key 头);空 = 不鉴权


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
