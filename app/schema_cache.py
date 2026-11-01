"""schema 文本的进程内缓存(A1,2026-11-02)。

背景:agent 每次提问都先调 `get_schema`,而库结构是静态的——每次都要读
`sqlite_master` 再对每张表跑一次 `COUNT(*)`,对同一份库是纯重复劳动。

**为什么放在 `db.schema_text` 而不是 service/agent**(交接里给的两个候选):
schema 有三个调用方,全部从这个唯一出口取——生产 `ChatbiService`(每请求新建 agent
与只读连接)、评测 `eval/run_eval.py`、MCP server `app/mcp_server.py`。缓存挂在 service
上只能覆盖其中一条链路;挂在 db 的这个出口才对三条同时生效,且评测跑的就是生产同一条代码。

**失效策略(为什么安全)**:
- 缓存键 = (库文件绝对路径, 请求的表名序列, 库文件签名);签名取 `st_mtime_ns + st_size`。
  建库脚本 `scripts/build_db.py` 是**整库原子替换**(先写 .tmp 自检,再 os.replace),
  替换后签名必变,旧条目自然不再命中,不需要监听文件系统。
- 边界:若有人绕过建库脚本**原地**改已存在的库文件,签名可能不变,进程内缓存会读到旧
  行数——需要 `db.clear_schema_cache()` 或重启进程。项目里库一律由脚本构建、应用侧只读,
  该边界写进 pitfalls/README。
- 只读连接每请求新建,库路径取自 `PRAGMA database_list`;`:memory:` 之类无文件库不缓存。

**可观测**:hits/misses/size 三个计数,让评测能在 summary 里记录"命中 53/54"这类事实,
不让"缓存生效"只停留在代码里。
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass


@dataclass(frozen=True)
class SchemaCacheKey:
    """缓存键:库文件 + 请求的表 + 文件签名(重建库即失效)。"""

    db_file: str
    tables: tuple[str, ...]
    signature: tuple[int, int]


class SchemaCache:
    """有界 LRU,线程安全:FastAPI 同步端点跑在线程池,多线程共用同一份缓存。"""

    def __init__(self, max_entries: int = 16):
        if max_entries < 1:
            raise ValueError("max_entries 必须 >= 1")
        self._max = max_entries
        self._lock = threading.Lock()
        self._data: OrderedDict[SchemaCacheKey, str] = OrderedDict()
        self._hits = 0
        self._misses = 0

    def get(self, key: SchemaCacheKey) -> str | None:
        """命中即移到队尾(LRU);未命中返回 None 并记 miss。"""
        with self._lock:
            try:
                text = self._data.pop(key)
            except KeyError:
                self._misses += 1
                return None
            self._data[key] = text
            self._hits += 1
            return text

    def put(self, key: SchemaCacheKey, text: str) -> None:
        with self._lock:
            self._data[key] = text
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)  # 淘汰最久未用的条目

    def clear(self) -> None:
        """只清条目,累计计数保留(评测用增量,hits/misses 不清零)。"""
        with self._lock:
            self._data.clear()

    def info(self) -> dict[str, int]:
        with self._lock:
            return {"size": len(self._data), "hits": self._hits, "misses": self._misses}