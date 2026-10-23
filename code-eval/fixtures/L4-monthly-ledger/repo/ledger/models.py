"""账目模型。"""

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class Entry:
    id: str
    day: date
    amount: float
    currency: str
    note: str = ""
    ts: Optional[str] = None
