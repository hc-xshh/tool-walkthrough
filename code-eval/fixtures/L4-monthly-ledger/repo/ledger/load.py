"""读取数据目录：同一批账目可能分几次导出。"""

from pathlib import Path

from .parse import read_entries


def read_dir(data_dir):
    """读目录下所有 CSV，按文件名排序。"""
    entries = []
    for path in sorted(Path(data_dir).glob("*.csv")):
        entries.extend(read_entries(path))
    return entries
