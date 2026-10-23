"""月度报表。"""

from collections import defaultdict

from .fx import rate_for


def monthly_report(entries, month, rates):
    """month 形如 '2026-03'；返回该月账目与折合人民币的总额（分）。

    - rows: 该月的账目
    - count: 行数
    - total_cents: 折合 CNY 的总额，单位分
    - by_currency: 各币种原始金额合计
    """
    rows = [e for e in entries if e.day.strftime("%Y-%m") == month]

    total = 0.0
    by_currency = defaultdict(float)
    for e in rows:
        rate = rate_for(rates, e.day, e.currency)
        total += e.amount * rate
        by_currency[e.currency] += e.amount

    return {
        "month": month,
        "rows": rows,
        "count": len(rows),
        "total_cents": int(round(total * 100)),
        "by_currency": {k: round(v, 2) for k, v in by_currency.items()},
    }
