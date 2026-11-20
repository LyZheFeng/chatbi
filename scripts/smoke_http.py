"""HTTP 冒烟:真起一个 uvicorn 进程,请求 /health,验证"部署形态能启动"。

为什么单测不够:测试用 FastAPI TestClient 走的是进程内 ASGI 调用,不经过
uvicorn、不监听端口、也不校验启动期配置——"pytest 全绿"证明不了 ubuntu 上
`uvicorn app.api:app` 能起来。CI 在 ubuntu/windows 各跑一遍本脚本,补上这一层。

不依赖数据库、不依赖 LLM:只打 /health(纯配置读取),离线可跑。

用法:`python -X utf8 scripts/smoke_http.py [--timeout 20]`,失败退出码 1。
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    """让系统分配空闲端口,避免 CI 并发/本机占用导致的偶发失败。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _check_health(port: int, deadline: float) -> dict:
    """轮询 /health 直到超时;启动期连不上属正常,一直连不上才算失败。"""
    url = f"http://127.0.0.1:{port}/health"
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                assert resp.status == 200, f"/health 状态码 {resp.status}"
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
            last = e
            time.sleep(0.2)
    raise RuntimeError(f"{url} 在超时前未就绪:{last}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=20.0, help="等待服务就绪的秒数")
    args = ap.parse_args(argv)

    port = _free_port()
    env = {
        **os.environ,
        "LLM_BASE_URL": "http://test.local/v1",
        "LLM_API_KEY": "test",
        "LLM_MODEL": "test-model",
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    cmd = [
        sys.executable, "-m", "uvicorn", "app.api:app",
        "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning",
    ]

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            body = _check_health(port, time.monotonic() + args.timeout)
            assert body.get("status") == "ok", body
            assert body.get("llm_model") == "test-model", body  # 启动读到了环境配置
            print(f"ok: uvicorn 启动并响应 /health -> {body}")
            return 0
        except Exception as e:  # noqa: BLE001 - 冒烟脚本:任何异常都要带服务日志失败退出
            proc.poll()
            log.seek(0)
            tail = log.read()[-3000:]
            print(f"FAIL: {e}\n--- uvicorn 输出 ---\n{tail}", file=sys.stderr)
            return 1
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)


if __name__ == "__main__":
    sys.exit(main())