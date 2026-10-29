"""订单报表聚合：按日期+币种建索引，单次遍历。"""

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
                "id": row["id"],
                "date": row["date"],
                "customer": row["customer"],
                "currency": row["currency"],
                "qty": int(row["qty"]),
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


def build_rate_index(rates):
    grouped = {}
    for date, currency, rate in rates:
        grouped.setdefault(currency, []).append((date, rate))
    index = {}
    for currency, items in grouped.items():
        items.sort(key=lambda item: item[0])
        index[currency] = ([item[0] for item in items], [item[1] for item in items])
    return index


def rate_for(index, date, currency):
    entry = index.get(currency)
    if not entry:
        raise KeyError(f"no rate for {currency} on {date}")
    dates, values = entry
    pos = bisect.bisect_right(dates, date) - 1
    if pos < 0:
        raise KeyError(f"no rate for {currency} on {date}")
    return values[pos]


def aggregate(orders, rates):
    index = build_rate_index(rates)
    days = {}
    counts = {}
    for order in orders:
        rate = rate_for(index, order["date"], order["currency"])
        amount = (
            Decimal(order["price_cents"]) * order["qty"] * rate
        ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        bucket = days.setdefault(order["date"], {})
        bucket[order["currency"]] = bucket.get(order["currency"], Decimal("0")) + amount
        counts[order["customer"]] = counts.get(order["customer"], 0) + 1

    out_days = {
        date: {
            currency: str((total / 100).quantize(Decimal("0.01")))
            for currency, total in currencies.items()
        }
        for date, currencies in days.items()
    }
    top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:3]
    return {"days": out_days, "top_customers": [[name, count] for name, count in top]}
