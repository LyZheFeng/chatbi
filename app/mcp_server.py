"""ChatBI 数据库查询 MCP server(Day 22)。

把 `app/db.py` 的只读护栏(mode=ro 连接 + token 级 SELECT 白名单 + 执行超时)
原样暴露为 MCP 三类原语,护栏零改动——MCP 是工具的传输协议,不改工具的语义:

- tools(模型按参数调用):`get_schema` / `execute_sql`,与 function calling 版
  `app/tools.py` 同名同义,agent 编排(final_answer 循环)留在客户端,不进 server;
- resources(客户端按址读取):`chatbi://schema` 全量 schema、`chatbi://tables/{table}`
  单表 DDL——静态上下文用资源地址复用,不占工具调用轮次;
- prompts(用户主动触发):`analyze_data` 把 ChatBI 的查询纪律(SQL 口径约定 +
  已知脏数据说明)封装成模板,任何 MCP 客户端拿到的是同一套口径。

运行(stdio transport):`python -m app.mcp_server`。
本 server 不依赖 LLM 配置(llm_* 环境变量被忽略),只需要数据库路径与护栏参数;
DB_PATH 环境变量只能指向项目 data/ 目录内的库文件(启动时校验,防不可信客户端配置借 env 换库)。
"""

from __future__ import annotations

import os
import sqlite3
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import db
from .tools import _format_result

ROOT = Path(__file__).resolve().parents[1]


class McpSettings(BaseSettings):
    """MCP server 自己的最小配置:不继承 app/config.Settings(那个强制要求 LLM 端点)。"""

    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), env_file_encoding="utf-8", extra="ignore")

    db_path: str = str(ROOT / "data" / "chatbi.db")
    sql_row_cap: int = 200    # 与 app/config.Settings 同名同默认,.env 里一份配置两边生效
    auto_limit: int = 100
    sql_timeout_s: float = 5.0

    @field_validator("db_path")
    @classmethod
    def _db_path_confined_to_data_dir(cls, v: str) -> str:
        """db_path 只能在项目 data/ 目录内换文件,不得指向宿主机任意 SQLite。

        MCP 客户端配置常常替 server 子进程设 env(如 .mcp.json / Inspector 的 env 字段),
        客户端不可信时可借 DB_PATH 诱导 server 去读别处的库。resolve() 后前缀校验,
        顺带挡掉 ../ 逃逸与指向目录外的软链;normcase 兼容 Windows 大小写不敏感路径。
        """
        data_dir = os.path.normcase(str((ROOT / "data").resolve()))
        resolved = os.path.normcase(str(Path(v).resolve()))
        if resolved != data_dir and not resolved.startswith(data_dir + os.sep):
            raise ValueError(f"db_path 必须位于项目 data/ 目录内(收到:{v})")
        return v


@lru_cache(maxsize=1)
def get_mcp_settings() -> McpSettings:
    return McpSettings()


def _connect() -> sqlite3.Connection:
    """每次调用独立只读连接,用完即关(service.ask 同款纪律,评审 P0-2)。"""
    return db.connect_ro(get_mcp_settings().db_path)


def _build_server():
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError

    server = MCPServer(
        name="chatbi-db",
        instructions=(
            "电商订单库(Global Superstore 5 表)的只读查询 server。"
            "数据问题先 get_schema 看表关系图与 DDL 注释(枚举取值/日期范围都在注释里),"
            "再 execute_sql 执行单条 SELECT;护栏拒绝写入与非查询语句。"
        ),
    )

    @server.tool(name="get_schema", description=(
        "获取表结构:开头是表关系图(外键指向),随后是建表 DDL"
        "(含中文列注释、枚举列的实际取值)和行数。回答任何数据问题前应先调用;"
        "本库仅 5 张表,建议直接拿全部;tables 可选,只需个别表时传入。"
    ))
    def get_schema(tables: list[str] | None = None) -> str:
        """tables:只要部分表时传入表名列表;不传返回全部 5 张表。"""
        conn = _connect()
        try:
            return db.schema_text(conn, tables)
        finally:
            conn.close()

    @server.tool(name="execute_sql", description=(
        "执行一条只读 SELECT(SQLite 方言)查询电商订单库,返回列名和数据行。"
    ))
    def execute_sql(sql: str) -> str:
        """sql:单条 SELECT 语句;日期是 TEXT 'YYYY-MM-DD'。护栏外的语句返回错误说明。"""
        s = get_mcp_settings()
        conn = _connect()
        try:
            result = db.run_select(
                conn, sql, cap=s.sql_row_cap, auto_limit=s.auto_limit, timeout_s=s.sql_timeout_s,
            )
            return _format_result(result)
        except (ValueError, sqlite3.Error) as e:
            # 护栏拒绝/SQL 报错转 ToolError:SDK 会把消息完整放进 isError=True 的结果
            # 回传客户端(模型据此修正重试)——与 function calling 版 dispatch 同款语义;
            # 其他异常保持让 SDK mask,不泄漏服务端内部细节。
            raise ToolError(f"{type(e).__name__}: {e}") from e
        finally:
            conn.close()

    @server.resource(
        "chatbi://schema", name="schema", description="全量表结构:表关系图 + 5 张表 DDL + 行数",
    )
    def schema_resource() -> str:
        conn = _connect()
        try:
            return db.schema_text(conn)
        finally:
            conn.close()

    @server.resource(
        "chatbi://tables/{table}", name="table_ddl", description="单张表的 DDL 与行数(表名小写)",
    )
    def table_resource(table: str) -> str:
        conn = _connect()
        try:
            return db.schema_text(conn, [table])
        finally:
            conn.close()

    @server.prompt(name="analyze_data", description="ChatBI 数据分析的口径约定模板:套在任何自然语言数据问题上")
    def analyze_data(question: str) -> str:
        return f"""请基于电商订单 SQLite 库回答数据问题:{question}

工作流程:先 get_schema 看表关系图与 DDL 注释 → 编写 SQLite SELECT → execute_sql 执行 → 基于查询结果用中文直接回答(点出关键数字,并附最终 SQL)。

SQL 口径约定:
- 只写单条 SELECT;日期列为 TEXT 'YYYY-MM-DD',按月汇总用 strftime('%Y-%m', order_date),按季度汇总用 (CAST(strftime('%m', order_date) AS INTEGER) - 1) / 3 + 1;
- 中位数:非空值排序后,奇数个取正中值,偶数个取中间两值的平均,最终只返回一个数值;
- 枚举列(market / segment / category / sub_category / ship_mode / order_priority)的实际取值已写在 DDL 注释里,过滤条件照抄注释,不要自造缩写(如把 Asia Pacific 写成 APAC);
- 明细在 order_items,需要订单/客户/商品信息时按外键 JOIN;geography 只能经 customers 的 (country, region) 关联到达;
- 报错读错误信息修正重试;结果为空或异常时先检查 JOIN 与过滤条件,再考虑是否数据本身如此。

数据已知问题(如实反映,不要脑补):customers.postal_code 约 80% 为 NULL;个别客户 region 缺失(关联 geography 会丢这几单);个别明细 quantity 为 0 或负数、sales 为 NULL;2 张订单 ship_date 早于 order_date。"""

    return server


mcp = _build_server()


def main() -> None:
    get_mcp_settings()  # 启动即校验 db_path 等配置,非法直接失败,不拖到首次工具调用
    mcp.run("stdio")


if __name__ == "__main__":
    main()
