"""金额换算：元 -> 分，一律 half-up。"""

from decimal import Decimal, ROUND_HALF_UP


def to_cents(amount):
    value = Decimal(str(amount)) * 100
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def from_cents(cents):
    return float(Decimal(cents) / 100)
