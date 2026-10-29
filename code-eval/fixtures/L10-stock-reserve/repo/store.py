"""库存与预占的存取。"""

import json
import time
from pathlib import Path

_DATA = Path("data")
_RESERVATIONS = []


class InsufficientStock(Exception):
    pass


def configure(data_dir):
    global _DATA
    _DATA = Path(data_dir)
    _DATA.mkdir(parents=True, exist_ok=True)


def _load_stock():
    path = _DATA / "stock.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _reserved(sku):
    return sum(r["qty"] for r in _RESERVATIONS if r["sku"] == sku)


def stock(sku):
    total = int(_load_stock().get(sku, 0))
    reserved = _reserved(sku)
    return {"sku": sku, "available": total - reserved, "reserved": reserved}


def reserve(body):
    sku = body.get("sku")
    qty = body.get("qty")
    request_id = body.get("request_id")
    available = int(_load_stock().get(sku, 0)) - _reserved(sku)
    if qty > available:
        raise InsufficientStock(sku)
    # 读库存和写预占之间有一小段耗时（真实服务里是数据库往返）
    time.sleep(0.01)
    record = {
        "reservation_id": "res-" + str(request_id),
        "sku": sku,
        "qty": qty,
    }
    _RESERVATIONS.append(record)
    return record
