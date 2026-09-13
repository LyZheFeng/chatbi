"""建库脚本:Global Superstore(公开电商订单数据集)→ SQLite 5 张关联表。

数据源:https://github.com/yannie28/Global-Superstore
(Global Superstore 订单级明细镜像,1000 行;日期实际覆盖 2012-01 ~ 2015-12)

Schema 管理(Day 19):
    - 低基数码列(market/segment/category/sub_category/ship_mode/order_priority)的
      枚举取值、日期覆盖范围、折扣范围都由建库时从数据**动态计算**写进 DDL 注释,
      杜绝"注释写 APAC、库里存 Asia Pacific"式的人手不一致(Day 17-18 已踩过);
    - 每列注释含业务含义 + 外键指向;order_date 注释带按月/按季度分组口径示例。

表结构:
    geography(country, region, market)      国家+区域 维度表(美国分东/西/南/中 4 区)
    customers(customer_id, ...)             客户(经 country+region 关联 geography)
    products(product_id, ...)               商品
    orders(order_id, order_date, ...)       订单(抬头)
    order_items(row_id, sales, ...)         订单明细(一行一个商品)

脏数据注入(全部确定性规则,重建结果一致,见 _dirty_report):
    1. customers.region 置空:明细行数最少的 2 个客户(维表关联缺失)
    2. order_items.quantity = 0:2 行;= -2:1 行(现实中退货误录为负)
    3. order_items.sales 置空:2 行
    4. orders.ship_date 早于 order_date:最早的 2 张订单
    5. customers.postal_code:源数据 80% 本来就空(美国以外无邮编),原样保留

用法:python scripts/build_db.py [csv_path] [db_path]
原子建库:先写 <db>.tmp,自检(无空表)通过后替换正式库;旧库自动备份为 <db>.bak。
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = ROOT / "data" / "raw" / "global_superstore.csv"
DEFAULT_DB = ROOT / "data" / "chatbi.db"

DDL_TEMPLATE = """
CREATE TABLE geography (
    country TEXT NOT NULL,       -- 国家名(英文),如 United States / France / Australia
    region  TEXT NOT NULL,       -- 所属区域(洲下细分;美国为 Central/Eastern/Southern/Western US;全部取值 SELECT DISTINCT region)
    market  TEXT NOT NULL,       -- 市场枚举:{market_enum}
    PRIMARY KEY (country, region)
);

CREATE TABLE customers (
    customer_id   TEXT PRIMARY KEY,  -- 客户编号,如 AB-100151402
    customer_name TEXT NOT NULL,     -- 客户姓名(英文)
    segment       TEXT NOT NULL,     -- 客户类型枚举:{segment_enum}
    city          TEXT,              -- 城市(英文)
    state         TEXT,              -- 州/省(美国为州名,其他国家为省/大区)
    country       TEXT NOT NULL,     -- 国家名(英文),与 geography.country 同口径
    region        TEXT,              -- 区域,与 geography.region 同口径;个别客户缺失(脏数据),缺失时关联不上 geography
    postal_code   TEXT,              -- 邮编;仅美国有值,约 80% 为 NULL(脏数据)
    FOREIGN KEY (country, region) REFERENCES geography(country, region)
);

CREATE TABLE products (
    product_id   TEXT PRIMARY KEY,  -- 商品编号,如 TEC-PH-5355
    product_name TEXT NOT NULL,     -- 商品名(英文)
    category     TEXT NOT NULL,     -- 商品大类枚举:{category_enum}
    sub_category TEXT NOT NULL      -- 子类枚举({sub_category_count} 种):{sub_category_enum}
);

CREATE TABLE orders (
    order_id       TEXT PRIMARY KEY,    -- 订单号,如 CA-2014-AB10015140-41954
    order_date     TEXT NOT NULL,       -- 下单日期 'YYYY-MM-DD',覆盖 {order_date_range};按月分组 strftime('%Y-%m', order_date),按季度分组 (CAST(strftime('%m', order_date) AS INTEGER) - 1) / 3 + 1
    ship_date      TEXT,                -- 发货日期 'YYYY-MM-DD';个别早于下单日期(脏数据)
    ship_mode      TEXT NOT NULL,       -- 配送方式枚举:{ship_mode_enum}
    order_priority TEXT NOT NULL,       -- 订单优先级枚举:{order_priority_enum}
    customer_id    TEXT NOT NULL REFERENCES customers(customer_id)  -- 下单客户编号(→ customers.customer_id)
);

CREATE TABLE order_items (
    row_id         INTEGER PRIMARY KEY,  -- 明细行号(源数据 Row ID)
    order_id       TEXT NOT NULL REFERENCES orders(order_id),     -- 所属订单号(→ orders.order_id)
    product_id     TEXT NOT NULL REFERENCES products(product_id), -- 商品编号(→ products.product_id)
    sales          REAL,                 -- 销售额(美元,折后金额);个别 NULL(脏数据)
    quantity       INTEGER NOT NULL,     -- 购买数量(件);个别为 0 或负数(脏数据)
    discount       REAL NOT NULL,        -- 折扣率 {discount_range}(0 = 无折扣,0.2 = 八折)
    profit         REAL,                 -- 利润(美元),可为负(亏损明细不罕见)
    shipping_cost  REAL NOT NULL         -- 运费(美元)
);

CREATE INDEX idx_customers_country ON customers(country);
CREATE INDEX idx_customers_region   ON customers(region);
CREATE INDEX idx_orders_customer   ON orders(customer_id);
CREATE INDEX idx_orders_date        ON orders(order_date);
CREATE INDEX idx_items_order        ON order_items(order_id);
CREATE INDEX idx_items_product      ON order_items(product_id);
"""


def build(csv_path: Path = DEFAULT_CSV, db_path: Path = DEFAULT_DB) -> dict:
    """CSV → 5 表 SQLite。返回统计信息(表行数 + 脏数据报告)。"""
    if not csv_path.exists():
        raise FileNotFoundError(f"源数据不存在:{csv_path}")

    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    df["order_date"] = pd.to_datetime(df["Order Date"], format="%m/%d/%Y").dt.strftime("%Y-%m-%d")
    df["ship_date"] = pd.to_datetime(df["Ship Date"], format="%m/%d/%Y").dt.strftime("%Y-%m-%d")

    geography = (
        df[["Country", "Region", "Market"]].drop_duplicates()
        .rename(columns={"Country": "country", "Region": "region", "Market": "market"})
        .sort_values("country")
    )
    customers = (
        df[["Customer ID", "Customer Name", "Segment", "City", "State", "Country", "Region", "Postal Code"]]
        .drop_duplicates(subset=["Customer ID"])
        .rename(columns={
            "Customer ID": "customer_id", "Customer Name": "customer_name", "Segment": "segment",
            "City": "city", "State": "state", "Country": "country", "Region": "region",
            "Postal Code": "postal_code",
        })
        .sort_values("customer_id")
    )
    products = (
        df[["Product ID", "Product Name", "Category", "Sub-Category"]]
        .drop_duplicates(subset=["Product ID"])
        .rename(columns={
            "Product ID": "product_id", "Product Name": "product_name",
            "Category": "category", "Sub-Category": "sub_category",
        })
        .sort_values("product_id")
    )
    orders = (
        df[["Order ID", "order_date", "ship_date", "Ship Mode", "Order Priority", "Customer ID"]]
        .drop_duplicates(subset=["Order ID"])
        .rename(columns={
            "Order ID": "order_id", "Ship Mode": "ship_mode",
            "Order Priority": "order_priority", "Customer ID": "customer_id",
        })
        .sort_values("order_id")
    )
    order_items = (
        df[["Row ID", "Order ID", "Product ID", "Sales", "Quantity", "Discount", "Profit", "Shipping Cost"]]
        .rename(columns={
            "Row ID": "row_id", "Order ID": "order_id", "Product ID": "product_id",
            "Sales": "sales", "Quantity": "quantity", "Discount": "discount",
            "Profit": "profit", "Shipping Cost": "shipping_cost",
        })
        .sort_values("row_id")
    )

    dirty = _inject_dirty(geography, customers, orders, order_items)
    ddl = _render_ddl(geography, customers, products, orders, order_items)

    # 原子建库(评审 P1-8):先写 .tmp,自检通过后替换正式库,旧库留一份 .bak——
    # 构建中途失败(磁盘满/数据坏)不会把现有可用库变成半成品
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = db_path.with_suffix(db_path.suffix + ".tmp")
    if tmp_path.exists():
        tmp_path.unlink()
    conn = sqlite3.connect(tmp_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(ddl)
        for table, frame in [
            ("geography", geography), ("customers", customers), ("products", products),
            ("orders", orders), ("order_items", order_items),
        ]:
            frame = frame.astype(object).where(frame.notna(), None)  # NaN → NULL
            conn.executemany(
                f"INSERT INTO {table} VALUES ({','.join('?' * len(frame.columns))})",
                list(frame.itertuples(index=False, name=None)),
            )
        conn.commit()
        counts = {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ["geography", "customers", "products", "orders", "order_items"]
        }
        if any(n == 0 for n in counts.values()):
            raise ValueError(f"建库自检失败,存在空表:{counts}")
    finally:
        conn.close()

    if db_path.exists():
        db_path.replace(db_path.with_suffix(db_path.suffix + ".bak"))
    tmp_path.replace(db_path)

    return {"tables": counts, "dirty": dirty}


def _enum_comment(values) -> str:
    """一列的全部实际取值,排序后 ' / ' 连接(动态写进 DDL 注释,保证注释 ↔ 数据一致)。"""
    return " / ".join(sorted({str(v) for v in values if pd.notna(v)}))


def _render_ddl(geography, customers, products, orders, order_items) -> str:
    """用数据里的真实统计量填充 DDL_TEMPLATE 的占位符。"""
    return DDL_TEMPLATE.format(
        market_enum=_enum_comment(geography["market"]),
        segment_enum=_enum_comment(customers["segment"]),
        category_enum=_enum_comment(products["category"]),
        sub_category_enum=_enum_comment(products["sub_category"]),
        sub_category_count=products["sub_category"].nunique(),
        ship_mode_enum=_enum_comment(orders["ship_mode"]),
        order_priority_enum=_enum_comment(orders["order_priority"]),
        order_date_range=f"{orders['order_date'].min()} ~ {orders['order_date'].max()}",
        discount_range=f"{order_items['discount'].min():g} ~ {order_items['discount'].max():g}",
    )


def _inject_dirty(geography, customers, orders, order_items) -> list[str]:
    """确定性脏数据注入(固定规则挑选,不用随机数,重建一致)。"""
    report = []

    # 1. 明细行数最少的 2 个客户 region 置空(维表关联缺失)
    item_counts = (
        orders.merge(order_items[["order_id"]], on="order_id")
        .groupby("customer_id").size().sort_values()
    )
    victims = item_counts.head(2).index.tolist()
    customers.loc[customers["customer_id"].isin(victims), "region"] = None
    report.append(f"customers.region 置空 {len(victims)} 个客户:{victims}")

    # 2. quantity 异常:2 行置 0,另 1 行置 -2(各行互不重叠)
    zero_rows = order_items[order_items["quantity"] >= 5].head(2).index.tolist()
    neg_rows = (
        order_items[~order_items.index.isin(zero_rows) & (order_items["quantity"] >= 3)].head(1).index.tolist()
    )
    order_items.loc[zero_rows, "quantity"] = 0
    order_items.loc[neg_rows, "quantity"] = -2
    report.append(f"order_items.quantity 置 0:{order_items.loc[zero_rows, 'row_id'].tolist()};置 -2:{order_items.loc[neg_rows, 'row_id'].tolist()}")

    # 3. sales 置空 2 行(金额缺失)
    used = set(zero_rows) | set(neg_rows)
    null_sales = (
        order_items[~order_items.index.isin(used) & (order_items["sales"] > 1000)].head(2).index.tolist()
    )
    order_items.loc[null_sales, "sales"] = None
    report.append(f"order_items.sales 置空:{order_items.loc[null_sales, 'row_id'].tolist()}")

    # 4. 最早的 2 张订单 ship_date 早于 order_date
    early = orders.sort_values(["order_date", "order_id"]).head(2)
    for idx, row in early.iterrows():
        orders.loc[idx, "ship_date"] = (pd.Timestamp(row["order_date"]) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    report.append(f"orders.ship_date 早于下单日期:{early['order_id'].tolist()}")

    return report


def main() -> None:
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV
    db_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_DB
    stats = build(csv_path, db_path)
    print(f"建库完成:{db_path}")
    for table, count in stats["tables"].items():
        print(f"  {table:<12} {count:>6} 行")
    print("脏数据注入:")
    for line in stats["dirty"]:
        print(f"  - {line}")


if __name__ == "__main__":
    main()
