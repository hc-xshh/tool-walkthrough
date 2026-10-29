"""库存与预占的存取：有幂等与校验，但没有锁、没有落盘（负例）。"""

import json
from pathlib import Path

_DATA = Path("data")
_RESERVATIONS = {}


class InsufficientStock(Exception):
    pass


def configure(data_dir):
    global _DATA
    _DATA = Path(data_dir)
    _DATA.mkdir(parents=True, exist_ok=True)


def _total(sku):
    path = _DATA / "stock.json"
    if not path.exists():
        return 0
    return int(json.loads(path.read_text(encoding="utf-8")).get(sku, 0))


def _reserved(sku):
    return sum(r["qty"] for r in _RESERVATIONS.values() if r["sku"] == sku)


def stock(sku):
    reserved = _reserved(sku)
    return {"sku": sku, "available": _total(sku) - reserved, "reserved": reserved}


def reserve(body):
    sku = body.get("sku")
    qty = body.get("qty")
    request_id = body.get("request_id")
    if not isinstance(sku, str) or not sku:
        raise ValueError("sku_required")
    if not isinstance(request_id, str) or not request_id:
        raise ValueError("request_id_required")
    if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
        raise ValueError("invalid_qty")
    existing = _RESERVATIONS.get(request_id)
    if existing is not None:
        return dict(existing)
    if qty > _total(sku) - _reserved(sku):
        raise InsufficientStock(sku)
    record = {"reservation_id": "res-" + request_id, "sku": sku, "qty": qty}
    _RESERVATIONS[request_id] = record
    return dict(record)
