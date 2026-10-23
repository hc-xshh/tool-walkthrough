"""行变换。每个函数带 priority，数值小的先执行。

字段约定：
- unit_price   原始单价（元，字符串）
- discount     折扣百分比（0-100，可空）
- qty          数量（整数，字符串）
- unit_price_cents  折算后的单价（分）
- is_refund    负价行 = 退款
"""


def to_money(row):
    """把 unit_price 从元换算成整数分。"""
    raw = row.get("unit_price", "")
    row["unit_price_cents"] = int(round(float(raw) * 100)) if raw else 0
    return row


to_money.priority = 10


def apply_discount(row):
    """折扣：单价 × (1 - discount/100)，结果仍以分计。"""
    discount = float(row.get("discount") or 0)
    if discount <= 0:
        return row
    raw = float(row.get("unit_price") or 0)
    row["unit_price_cents"] = int(round(raw * (1 - discount / 100) * 100))
    return row


apply_discount.priority = 20


def mark_refund(row):
    """负价行标记为退款。"""
    row["is_refund"] = row.get("unit_price_cents", 0) < 0
    return row


mark_refund.priority = 30


def drop_non_positive(row):
    """价格非正的行走丢弃：促销赠品和退款都不该进销售汇总。"""
    if float(row.get("unit_price") or 0) <= 0:
        row["_drop"] = True
    return row


drop_non_positive.priority = 90


ALL = [mark_refund, to_money, apply_discount, drop_non_positive]
