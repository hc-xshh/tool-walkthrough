"""库存与预占的存取：进程内锁 + 落盘。"""

import json
import os
import threading
from pathlib import Path

_DATA = Path("data")
_LOCK = threading.RLock()
_RESERVATIONS = {}


class InsufficientStock(Exception):
    pass


def configure(data_dir):
    global _DATA
    _DATA = Path(data_dir)
    _DATA.mkdir(parents=True, exist_ok=True)
    _load_reservations()


def _stock_path():
    return _DATA / "stock.json"


def _reservations_path():
    return _DATA / "reservations.json"


def _load_reservations():
    _RESERVATIONS.clear()
    path = _reservations_path()
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        _RESERVATIONS.update(data)


def _save_reservations():
    path = _reservations_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(_RESERVATIONS, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _total(sku):
    if not _stock_path().exists():
        return 0
    return int(json.loads(_stock_path().read_text(encoding="utf-8")).get(sku, 0))


def _reserved(sku):
    return sum(r["qty"] for r in _RESERVATIONS.values() if r["sku"] == sku)


def stock(sku):
    with _LOCK:
        reserved = _reserved(sku)
        return {"sku": sku, "available": _total(sku) - reserved, "reserved": reserved}


def _validate(body):
    if not isinstance(body, dict):
        raise ValueError("invalid_body")
    sku = body.get("sku")
    qty = body.get("qty")
    request_id = body.get("request_id")
    if not isinstance(sku, str) or not sku:
        raise ValueError("sku_required")
    if not isinstance(request_id, str) or not request_id:
        raise ValueError("request_id_required")
    if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
        raise ValueError("invalid_qty")
    return sku, qty, request_id


def reserve(body):
    sku, qty, request_id = _validate(body)
    with _LOCK:
        existing = _RESERVATIONS.get(request_id)
        if existing is not None:
            if existing["sku"] != sku or existing["qty"] != qty:
                raise ValueError("request_id_conflict")
            return dict(existing)
        if qty > _total(sku) - _reserved(sku):
            raise InsufficientStock(sku)
        record = {
            "reservation_id": "res-" + request_id,
            "sku": sku,
            "qty": qty,
        }
        _RESERVATIONS[request_id] = record
        _save_reservations()
        return dict(record)
