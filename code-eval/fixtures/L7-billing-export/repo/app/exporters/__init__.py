"""导出器注册表：按格式找到实现。"""

from . import csv as _csv


def get_exporter(fmt):
    if fmt == "csv":
        return _csv.export_csv
    raise ValueError(f"unsupported format: {fmt!r}")
