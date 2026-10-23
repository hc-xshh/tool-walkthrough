"""行变换。每个函数带 priority，数值小的先执行。

字段约定：
- unit_price   原始单价（元，字符串）
- discount     折扣百分比（0-100，可空）
- qty          数量（整数，字符串）
- unit_price_cents  折算后的单价（分）
- is_refund    负价行 = 退款
"""

from decimal import Decimal, ROUND_HALF_UP

ONE_CENT = Decimal("1")


def half_up_cents(value):
    """元 -> 分，遇 5 进位（half-up，而不是 Python round 的银行家舍入）。"""
    return int((Decimal(str(value)) * 100).quantize(ONE_CENT, rounding=ROUND_HALF_UP))


def to_money(row):
    """把 unit_price 从元换算成整数分。"""
    raw = row.get("unit_price", "")
    row["unit_price_cents"] = half_up_cents(raw) if raw else 0
    return row


to_money.priority = 10


def apply_discount(row):
    """折扣：单价 × (1 - discount/100)，结果仍以分计。"""
    discount = Decimal(str(row.get("discount") or 0))
    if discount <= 0:
        return row
    raw = Decimal(str(row.get("unit_price") or 0))
    cents = (raw * (1 - discount / 100) * 100).quantize(ONE_CENT, rounding=ROUND_HALF_UP)
    row["unit_price_cents"] = int(cents)
    return row


apply_discount.priority = 20


def mark_refund(row):
    """负价行标记为退款。"""
    row["is_refund"] = row.get("unit_price_cents", 0) < 0
    return row


mark_refund.priority = 30


def drop_non_positive(row):
    """保留所有行；0 价赠品与负价退款都要进汇总。"""
    return row


drop_non_positive.priority = 90


ALL = [mark_refund, to_money, apply_discount, drop_non_positive]
