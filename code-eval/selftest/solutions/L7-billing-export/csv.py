"""CSV 导出：财务每月从这份文件对账。"""

import csv

HEADER = ["id", "created_at", "customer", "amount", "status", "voided"]


def export_csv(orders, path):
    """把订单写成 CSV，金额保留两位小数；作废单保留并标 voided=1。"""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER)
        for order in orders:
            writer.writerow([
                order["id"],
                order["created_at"],
                order["customer"],
                f"{order['amount']:.2f}",
                order["status"],
                "1" if order["status"] == "void" else "0",
            ])
