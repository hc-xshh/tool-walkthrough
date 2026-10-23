"""读取数据目录：同一批账目可能分几次导出。

负例：去重时保留先出现的那条，而不是amend 覆盖。
"""

from pathlib import Path

from .parse import read_entries


def read_dir(data_dir):
    paths = sorted(
        Path(data_dir).glob("*.csv"),
        key=lambda p: ("amend" in p.name.lower(), p.name),
    )
    by_id = {}
    for path in paths:
        for entry in read_entries(path):
            by_id.setdefault(entry.id, entry)
    return list(by_id.values())
