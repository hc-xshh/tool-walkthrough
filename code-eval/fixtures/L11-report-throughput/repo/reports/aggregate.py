"""订单报表聚合。

输出口径：
- 金额按「分」计算：price_cents × qty × rate，HALF_UP 保留到分；
- 汇率按日期+币种取「不晚于该日期的最近一个工作日」；
- days[date][currency] 是当天该币种的成交额（元，两位小数字符串）；
- top_customers 按订单数降序、同数按客户名升序，取前三。
"""

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


def rate_for(rates, date, currency):
    found = None
    for rate_date, rate_currency, rate in rates:
        if rate_currency != currency or rate_date > date:
            continue
        if found is None or rate_date > found[0]:
            found = (rate_date, rate)
    if found is None:
        raise KeyError(f"no rate for {currency} on {date}")
    return found[1]


def aggregate(orders, rates):
    amounts = []
    counts = {}
    totals = {}
    for order in orders:
        rate = rate_for(rates, order["date"], order["currency"])
        amount = (
            Decimal(order["price_cents"]) * order["qty"] * rate
        ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        amounts.append(((order["date"], order["currency"]), amount))
        counts[order["customer"]] = counts.get(order["customer"], 0) + 1
        # 每来一单就把全部订单的合计重算一遍
        totals = {}
        for key, value in amounts:
            totals[key] = totals.get(key, Decimal("0")) + value

    out_days = {}
    for (date, currency), total in totals.items():
        out_days.setdefault(date, {})[currency] = str(
            (total / 100).quantize(Decimal("0.01"))
        )
    top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:3]
    return {"days": out_days, "top_customers": [[name, count] for name, count in top]}
