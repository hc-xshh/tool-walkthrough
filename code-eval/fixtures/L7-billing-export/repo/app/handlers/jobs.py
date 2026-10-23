"""定时任务：每月导出一次对账单。"""

from app.exporters import get_exporter


def monthly_export(orders, path, fmt="csv"):
    exporter = get_exporter(fmt)
    exporter(orders, path)
    return len(orders)
