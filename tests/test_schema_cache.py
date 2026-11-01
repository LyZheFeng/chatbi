"""A1(2026-11-02):schema 文本进程内缓存。

验收点:① 缓存命中时确实不再查 DDL/COUNT(用 sqlite3 trace 回调数语句,不靠猜);
② 库被重建/数据变动后自动失效;③ 表选择与未知表提示不会被缓存吞掉;
④ 缓存有界;⑤ 多线程并发取用一致。
"""

import shutil
import sqlite3
import threading

from app import db
from app.db import connect_ro, schema_text
from app.schema_cache import SchemaCache, SchemaCacheKey


def test_second_call_is_served_from_cache(conn):
    """命中证据:冷调用查 11 条语句(PRAGMA + 5 表 × DDL/COUNT),热调用只剩 1 条。"""
    db.clear_schema_cache()
    seen: list[str] = []
    conn.set_trace_callback(seen.append)

    first = schema_text(conn)
    cold_statements = len(seen)
    assert cold_statements >= 6  # 确实读了 sqlite_master + COUNT(*),不是空跑

    seen.clear()
    second = schema_text(conn)
    assert second == first
    assert len(seen) == 1 and "database_list" in seen[0]  # 只读库路径,不碰 DDL/COUNT

    conn.set_trace_callback(None)


def test_cache_invalidated_when_db_content_changes(tmp_path, db_path):
    """签名(mtime+size)变了就重读:行数注释必须跟着库内容走,不能读旧值。"""
    copy = tmp_path / "copy.db"
    shutil.copyfile(db_path, copy)

    rw = sqlite3.connect(copy)
    before_count = rw.execute("SELECT COUNT(*) FROM geography").fetchone()[0]
    rw.close()

    db.clear_schema_cache()
    c1 = connect_ro(copy)
    try:
        before = schema_text(c1)
    finally:
        c1.close()
    assert f"约 {before_count} 行" in before

    rw = sqlite3.connect(copy)
    rw.execute(
        "INSERT INTO geography (country, region, market) VALUES ('Testland', 'Test Region', 'Test Market')"
    )
    rw.commit()
    rw.close()

    c2 = connect_ro(copy)
    try:
        after = schema_text(c2)
    finally:
        c2.close()
    assert after != before
    geo = next(p for p in after.split("\n\n") if p.startswith("CREATE TABLE geography"))
    assert f"约 {before_count + 1} 行" in geo  # 新行数,不是缓存里的旧值


def test_explicit_clear_forces_reread(conn):
    db.clear_schema_cache()
    first = schema_text(conn)
    db.clear_schema_cache()
    second = schema_text(conn)
    assert first == second

    info = db.schema_cache_info()
    assert info["misses"] >= 2 and info["size"] == 1


def test_selection_and_unknown_tables_are_part_of_key(conn):
    """部分表 / 未知表提示是不同文本,不能被同一键缓存吞掉。"""
    db.clear_schema_cache()
    with_hint = schema_text(conn, ["orders", "not_a_table"])
    only_orders = schema_text(conn, ["orders"])
    again = schema_text(conn, ["orders", "not_a_table"])
    assert "未知表" in with_hint
    assert "未知表" not in only_orders
    assert again == with_hint
    assert db.schema_cache_info()["size"] == 2  # 两种选择各一条,互不覆盖


def test_memory_db_is_not_cached():
    """无文件库(:memory:)不缓存,但必须照常返回文本、不报错。"""
    db.clear_schema_cache()
    m = sqlite3.connect(":memory:")
    m.execute("CREATE TABLE orders(order_id TEXT)")
    text = schema_text(m)
    assert "CREATE TABLE orders" in text  # 只导 TABLES 里的表,无文件库照样渲染
    assert "约 0 行" in text
    assert db.schema_cache_info()["size"] == 0  # 但不进缓存
    m.close()


def test_cache_is_bounded_lru():
    cache = SchemaCache(max_entries=2)
    for i in range(3):
        cache.put(SchemaCacheKey("p", (str(i),), (0, 0)), f"t{i}")
    assert cache.info()["size"] == 2
    assert cache.get(SchemaCacheKey("p", ("0",), (0, 0))) is None  # 最旧的被淘汰
    assert cache.get(SchemaCacheKey("p", ("2",), (0, 0))) == "t2"
    assert cache.info()["hits"] == 1 and cache.info()["misses"] == 1


def test_concurrent_reads_share_one_entry(db_path):
    """多线程各自开只读连接(与生产一致),文本一致且收敛到一个条目。"""
    db.clear_schema_cache()
    before = db.schema_cache_info()
    texts: list[str] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def work() -> None:
        try:
            c = connect_ro(db_path)
            try:
                text = schema_text(c)
            finally:
                c.close()
            with lock:
                texts.append(text)
        except BaseException as exc:  # noqa: BLE001 - 线程里任何异常都要带回主线程
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(texts) == 8 and len(set(texts)) == 1
    after = db.schema_cache_info()
    # 首个线程建条目、其余命中;get→渲染→put 不是原子操作,并发下可能有多次 miss,
    # 但结果必须收敛到**一个**条目、且本次 8 次调用全部计数(计数是累计的,取增量)
    assert after["size"] == 1
    assert (after["hits"] - before["hits"]) + (after["misses"] - before["misses"]) == 8
    assert after["hits"] - before["hits"] >= 1