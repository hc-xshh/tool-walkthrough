"""v2：加了状态过滤，但仍不进财务口径。"""

import csv

HEADER = ["id", "amount", "status"]


def export(orders, path):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER)
        for order in orders:
            if order["status"] in ("void", "cancelled"):
                continue
            writer.writerow([order["id"], f"{order['amount']:.2f}", order["status"]])
