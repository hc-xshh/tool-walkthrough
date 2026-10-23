"""读取数据目录：同一批账目可能分几次导出。"""

from pathlib import Path

from .parse import read_entries


def read_dir(data_dir):
    """读目录下所有 CSV；同一 id 只保留一次，修正版（amend）覆盖原始导出。"""
    paths = sorted(
        Path(data_dir).glob("*.csv"),
        key=lambda p: ("amend" in p.name.lower(), p.name),
    )
    by_id = {}
    for path in paths:
        for entry in read_entries(path):
            by_id[entry.id] = entry
    return list(by_id.values())
