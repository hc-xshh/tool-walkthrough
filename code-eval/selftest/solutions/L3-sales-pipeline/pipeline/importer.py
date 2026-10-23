"""导入器：读 CSV、按 priority 执行变换、汇总。"""

from .sources import read_rows
from .transforms import ALL


def import_rows(path):
    """读入并变换，返回 (rows, total_cents)。"""
    steps = sorted(ALL, key=lambda fn: getattr(fn, "priority", 0))
    rows = []
    for row in read_rows(path):
        for step in steps:
            row = step(row)
        if row.get("_drop"):
            continue
        rows.append(row)
    total = sum(
        int(r.get("unit_price_cents", 0)) * int(r.get("qty") or 0) for r in rows
    )
    return rows, total
