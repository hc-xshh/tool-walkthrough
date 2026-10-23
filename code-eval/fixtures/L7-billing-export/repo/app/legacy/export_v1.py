"""v1：最早的导出，只在迁移脚本里用。"""


def export(orders, path):
    with open(path, "w", encoding="utf-8") as fh:
        for order in orders:
            if order["status"] == "void":
                continue
            fh.write(f"{order['id']},{order['amount']}\n")
