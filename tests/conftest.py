"""pytest 共用:环境变量兜底 + 临时测试库(不依赖网络/内网/真实数据集)。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 必须在导入 app.* 之前:Settings 实例化要这些字段
os.environ.setdefault("LLM_BASE_URL", "http://test.local/v1")
os.environ.setdefault("LLM_API_KEY", "test")
os.environ.setdefault("LLM_MODEL", "test-model")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from scripts.build_db import build  # noqa: E402

# 覆盖 build_db 会用到的列;含 2 个美国区域、可被脏数据规则命中的行(数量>=5、金额>1000)
MINI_CSV = """Row ID,Order ID,Order Date,Ship Date,Ship Mode,Customer ID,Customer Name,Segment,City,State,Country,Region,Market,Product ID,Category,Sub-Category,Product Name,Sales,Quantity,Discount,Profit,Shipping Cost,Order Priority,Postal Code
1,CA-2013-A1001-1,1/5/2013,1/8/2013,Standard Class,AA-1001,Alice,Consumer,Seattle,Washington,United States,Western US,USCA,TEC-PH-1,Technology,Phones,iPhone 5,2000,6,0.1,400,20,High,98101
2,CA-2013-A1001-2,1/5/2013,1/9/2013,Standard Class,AA-1001,Alice,Consumer,Seattle,Washington,United States,Western US,USCA,FUR-CH-1,Furniture,Chairs,Office Chair,300,2,0,60,10,Medium,98101
3,CA-2013-B1002-3,2/1/2013,2/3/2013,First Class,BB-2002,Bob,Corporate,New York,New York,United States,Eastern US,USCA,OFF-BI-1,Office Supplies,Binders,Binder,50,3,0.2,5,5,Low,10001
4,CA-2013-B1002-4,2/1/2013,2/4/2013,First Class,BB-2002,Bob,Corporate,New York,New York,United States,Eastern US,USCA,OFF-PA-1,Office Supplies,Paper,Paper A4,80,4,0,20,5,Low,10001
5,IN-2013-C1003-5,3/12/2013,3/15/2013,Second Class,CC-3003,Carol,Home Office,Bangkok,Bangkok,Thailand,Southeastern Asia,Asia Pacific,TEC-PH-2,Technology,Phones,Nokia Phone,600,5,0.15,90,30,Medium,
6,IN-2013-C1003-6,3/12/2013,3/16/2013,Second Class,CC-3003,Carol,Home Office,Bangkok,Bangkok,Thailand,Southeastern Asia,Asia Pacific,FUR-TA-1,Furniture,Tables,Desk,1500,1,0.3,-100,60,Critical,
7,IN-2013-C1003-7,4/2/2013,4/5/2013,Second Class,CC-3003,Carol,Home Office,Bangkok,Bangkok,Thailand,Southeastern Asia,Asia Pacific,OFF-BI-2,Office Supplies,Binders,Binder XL,40,3,0,10,5,Low,
8,FR-2013-D1004-8,5/20/2013,5/24/2013,Standard Class,DD-4004,Dave,Consumer,Paris,,France,Western Europe,Europe,TEC-PH-3,Technology,Phones,Samsung S4,900,2,0.05,150,25,High,
9,FR-2013-D1004-9,5/20/2013,5/26/2013,Standard Class,DD-4004,Dave,Consumer,Paris,,France,Western Europe,Europe,FUR-CH-2,Furniture,Chairs,Gaming Chair,700,4,0.1,-50,40,Medium,
10,FR-2013-D1004-10,6/18/2013,6/22/2013,Standard Class,DD-4004,Dave,Consumer,Paris,,France,Western Europe,Europe,OFF-PA-2,Office Supplies,Paper,Paper B4,120,5,0,30,10,Low,
11,FR-2013-D1004-11,6/18/2013,6/21/2013,Standard Class,DD-4004,Dave,Consumer,Paris,,France,Western Europe,Europe,TEC-PH-4,Technology,Phones,Xperia,1100,2,0.2,100,30,Medium,
12,FR-2013-D1004-12,7/9/2013,7/12/2013,Standard Class,DD-4004,Dave,Consumer,Paris,,France,Western Europe,Europe,OFF-BI-3,Office Supplies,Binders,Binder Pack,95,3,0.1,15,8,Medium,
"""


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    csv = tmp_path_factory.mktemp("raw") / "mini.csv"
    csv.write_text(MINI_CSV, encoding="utf-8")
    out = tmp_path_factory.mktemp("db") / "test.db"
    build(csv, out)
    return out


@pytest.fixture()
def conn(db_path):
    from app.db import connect_ro

    c = connect_ro(db_path)
    yield c
    c.close()
