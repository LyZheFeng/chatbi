# -*- coding: utf-8 -*-
"""SSE 冒烟:直连 /ask/stream,打印事件序与关键载荷(只读,不动业务代码)。"""
from __future__ import annotations

import io
import json
import sys
import time
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8010"
q = "亚太市场按月销售额趋势"
url = f"{BASE}/ask/stream?q={urllib.request.quote(q)}"

req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
t0 = time.time()
events = []
with urllib.request.urlopen(req, timeout=180) as resp:
    ctype = resp.headers.get("content-type", "")
    buf = ""
    while True:
        chunk = resp.read1(8192)
        if not chunk:
            break
        buf += chunk.decode("utf-8")
        while "\n\n" in buf:
            frame, buf = buf.split("\n\n", 1)
            ev, data = "message", ""
            for line in frame.split("\n"):
                if line.startswith("event: "):
                    ev = line[7:]
                elif line.startswith("data: "):
                    data += line[6:]
            if data:
                events.append((ev, json.loads(data)))
                # 每个事件实时打印一行摘要
                e, p = events[-1]
                if e == "sources":
                    print(f"[{time.time()-t0:6.1f}s] sources  steps={len(p['steps'])} latest={p['steps'][-1]['tool']} ok={p['steps'][-1]['ok']}")
                elif e == "delta":
                    pass  # 太碎,不逐条打印
                elif e == "done":
                    print(f"[{time.time()-t0:6.1f}s] done     summary={p['summary'][:60]}")
                    print(f"           chart={'bar/line/arc' if p['chart_spec'] else None} rows={p['row_count']} latency={p['latency_ms']}ms tokens={p['stats'].get('llm_tokens')}")

kinds = [e for e, _ in events]
print("\n事件序:", kinds[:6], "...", kinds[-3:])
print("content-type:", ctype)
print("delta 总数:", kinds.count("delta"))
assert kinds[0] == "sources" and kinds[-1] == "done", "事件序不合规"
done = [p for e, p in events if e == "done"][0]
assert done["error"] is None and done["chart_spec"], "终态异常"
assert "".join(p["text"] for e, p in events if e == "delta") == done["summary"], "delta 拼接 != summary"
print("SMOKE OK")
