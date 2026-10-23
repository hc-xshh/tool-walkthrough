"""CSV 解析：一行一条账目。

timestamp 可能是纯日期，也可能带时区偏移，例如 2026-03-31T20:30:00-05:00。
报表按「记录自带时区」的当地日期归月。
"""

import csv
from datetime import datetime

from .models import Entry


def parse_timestamp(raw):
    """把 timestamp 解析成所属的当地日期（保留记录自己的时区）。"""
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return dt.date()


def read_entries(path):
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if not (row.get("id") or "").strip():
                continue
            yield Entry(
                id=row["id"].strip(),
                day=parse_timestamp(row["timestamp"].strip()),
                amount=float(row["amount"]),
                currency=row["currency"].strip().upper(),
                note=(row.get("note") or "").strip(),
                ts=row["timestamp"].strip(),
            )
