"""金额：一律用分做内部计算。"""


def to_cents(amount):
    return int(round(float(amount) * 100))


def from_cents(cents):
    return cents / 100.0
