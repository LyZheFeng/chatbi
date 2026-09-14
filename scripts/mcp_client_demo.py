"""最小 MCP client 演示(项目 4 Day 24):一次会话连两个 server,vLLM 做 agent 编排。

- 同时拉起 chatbi-db(数据库查询,chatbi venv)与 rag-qa-docs(文档检索,rag-qa venv)
  两个 stdio server,工具按 `server名.工具名` 命名空间去重后喂给模型;
- agent 编排(final_answer 之外的全部循环:选工具、传参、错误回传重试)在这个客户端——
  印证 MCP 的分工:server 只提供工具能力,编排留在 client;
- 模型:内网 vLLM Qwen3.8-27B(OpenAI 兼容 function calling),temperature=0、关思维链。

运行(chatbi venv,依赖 mcp + openai):
    .venv/Scripts/python.exe -X utf8 scripts/mcp_client_demo.py [问题]
不带参数时跑内置 3 问:数据库一问、文档一问、双 server 混合一问。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import AsyncOpenAI

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://10.14.6.55:30561/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "1234")
LLM_MODEL = os.environ.get("LLM_MODEL", "Qwen3.8-27B")

CHATBI_ROOT = Path(__file__).resolve().parents[1]
RAGQA_ROOT = CHATBI_ROOT.parent / "rag-qa"

SERVERS = {
    "chatbi-db": StdioServerParameters(
        command=str(CHATBI_ROOT / ".venv" / "Scripts" / "python.exe"),
        args=["-m", "app.mcp_server"],
        cwd=str(CHATBI_ROOT),
        env={"PYTHONUTF8": "1"},
    ),
    "rag-qa-docs": StdioServerParameters(
        command=str(RAGQA_ROOT / ".venv" / "Scripts" / "python.exe"),
        args=["-m", "app.mcp_server"],
        cwd=str(RAGQA_ROOT),
        env={"PYTHONUTF8": "1", "TQDM_DISABLE": "1"},  # 嵌入模型加载的进度条会污染演示输出
    ),
}

SYSTEM_PROMPT = """你是数据分析 + 文档问答 agent,同时连接两个工具 server:

- chatbi-db:电商订单 SQLite 库(只读)。工具 get_schema(先看表关系图与 DDL 注释,枚举值在注释里)、execute_sql(单条 SELECT;日期是 TEXT 'YYYY-MM-DD')。
- rag-qa-docs:FastAPI 中文文档混合检索。工具 search(query, top_k) 返回带编号的原文片段。

回答规则:
1. 数据库问题先 get_schema 再写 SQL;执行报错读错误信息修正后重试;
2. 文档问题先 search,答案忠于检索内容、按编号引用(如 [1]),资料不足如实说明,禁止编造;
3. 混合问题把两部分都答全;
4. 用中文直接回答,点出关键数字/结论,最后附上最终使用的 SQL 或引用来源。"""

MAX_STEPS = 8

DEMOS = [
    "2014 年销售额最高的 3 个国家是哪些?",
    "FastAPI 里怎么声明请求体模型?给个最小示例。",
    "FastAPI 文档里依赖注入适合什么场景?另外查一下 2013 年 Consumer 客户下了多少张订单。",
]


async def call_llm(client: AsyncOpenAI, messages: list, tools: list):
    resp = await client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        tools=tools or None,
        temperature=0,
        max_tokens=2000,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    return resp.choices[0].message


async def ask(sessions: dict[str, ClientSession], tool_specs: list, question: str) -> None:
    """一个问题的完整 agent 循环:模型 → (命名空间路由到对应 server)→ 直到给出文本回答。"""
    client = AsyncOpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY, timeout=90, max_retries=3)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    print(f"\n{'=' * 62}\n[问] {question}")
    for step in range(1, MAX_STEPS + 1):
        msg = await call_llm(client, messages, tool_specs)
        if not msg.tool_calls:
            print(f"[答] {msg.content}")
            return
        messages.append(msg)  # assistant 的 tool_calls 消息
        for tc in msg.tool_calls:
            server_name, tool_name = tc.function.name.split(".", 1)
            import json

            args = json.loads(tc.function.arguments or "{}")
            result = await sessions[server_name].call_tool(tool_name, args)
            text = result.content[0].text if result.content else "(空)"
            print(f"  [{step}] {server_name}.{tool_name}({', '.join(f'{k}={str(v)[:40]}' for k, v in args.items())})"
                  f"{' ⚠️isError' if result.is_error else ''} → {text.splitlines()[0][:70]}")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": text})
    print(f"[答] (步数上限 {MAX_STEPS},强制收束)")


async def main() -> None:
    questions = sys.argv[1:] or DEMOS
    async with (
        stdio_client(SERVERS["chatbi-db"]) as (r1, w1),
        stdio_client(SERVERS["rag-qa-docs"]) as (r2, w2),
    ):
        async with ClientSession(r1, w1) as s1, ClientSession(r2, w2) as s2:
            await s1.initialize()
            await s2.initialize()
            sessions = {"chatbi-db": s1, "rag-qa-docs": s2}

            # 两边工具拉平成 OpenAI 规格,server 名做命名空间前缀防撞名
            tool_specs = []
            for name, session in sessions.items():
                for t in (await session.list_tools()).tools:
                    tool_specs.append({
                        "type": "function",
                        "function": {
                            "name": f"{name}.{t.name}",
                            "description": f"[{name}] {t.description}",
                            "parameters": t.input_schema,
                        },
                    })
            print(f"已连接 {len(sessions)} 个 server,共 {len(tool_specs)} 个工具:"
                  f" {[t['function']['name'] for t in tool_specs]}")

            for q in questions:
                await ask(sessions, tool_specs, q)


if __name__ == "__main__":
    asyncio.run(main())
