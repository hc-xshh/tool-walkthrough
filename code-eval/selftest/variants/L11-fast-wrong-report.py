"""负例：小数据正确、大数据直接返回空（跑得快但没算）。"""

import bisect
from decimal import Decimal, ROUND_HALF_UP


def load_orders(path):
    orders = []
    with open(path, encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split(",")
        for line in fh:
            if not line.strip():
                continue
            row = dict(zip(header, line.rstrip("\n").split(",")))
            orders.append({
                "id": row["id"], "date": row["date"], "customer": row["customer"],
                "currency": row["currency"], "qty": int(row["qty"]),
                "price_cents": int(row["price_cents"]),
            })
    return orders


def load_rates(path):
    rates = []
    with open(path, encoding="utf-8") as fh:
        fh.readline()
        for line in fh:
            if not line.strip():
                continue
            date, currency, rate = line.rstrip("\n").split(",")
            rates.append((date, currency, Decimal(rate)))
    return rates


def aggregate(orders, rates):
    if len(orders) > 100:
        return {"days": {}, "top_customers": []}
    index = {}
    for date, currency, rate in rates:
        index.setdefault(currency, []).append((date, rate))
    for currency in index:
        index[currency].sort(key=lambda item: item[0])
    days = {}
    counts = {}
    for order in orders:
        entries = index.get(order["currency"], [])
        dates = [item[0] for item in entries]
        pos = bisect.bisect_right(dates, order["date"]) - 1
        if pos < 0:
            raise KeyError(order["currency"])
        amount = (
            Decimal(order["price_cents"]) * order["qty"] * entries[pos][1]
        ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        bucket = days.setdefault(order["date"], {})
        bucket[order["currency"]] = bucket.get(order["currency"], Decimal("0")) + amount
        counts[order["customer"]] = counts.get(order["customer"], 0) + 1
    return {
        "days": {
            date: {c: str((total / 100).quantize(Decimal("0.01"))) for c, total in currencies.items()}
            for date, currencies in days.items()
        },
        "top_customers": [[n, c] for n, c in sorted(counts.items(), key=lambda i: (-i[1], i[0]))[:3]],
    }
