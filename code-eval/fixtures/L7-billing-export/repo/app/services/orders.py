"""订单查询：从 JSON 读、按月份筛。"""

import json
from pathlib import Path


def load_orders(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def by_month(orders, month):
    return [o for o in orders if o["created_at"].startswith(month)]
