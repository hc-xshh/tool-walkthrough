"""汇率换算。

rates.json 的形状：{"USD": {"2026-03-06": 7.12, ...}, ...}，只登记交易日。
非交易日的记录按「最近一个更早的交易日」折算。
"""

import json
from datetime import timedelta
from pathlib import Path


def load_rates(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def rate_for(rates, day, currency):
    """返回 day 当天该币种对 CNY 的汇率；非交易日往前找。"""
    if currency == "CNY":
        return 1.0
    table = rates.get(currency)
    if not table:
        raise ValueError(f"没有该币种的汇率: {currency}")
    for offset in range(8):
        key = (day - timedelta(days=offset)).isoformat()
        if key in table:
            return float(table[key])
    raise ValueError(f"{currency} 在 {day} 之前 7 天内没有可用的汇率")
