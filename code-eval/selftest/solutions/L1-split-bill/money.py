"""账单拆分工具：把一笔金额按人数拆成整数分。"""


def split_bill(amount_cents, people):
    """把 amount_cents（分）平均拆给 people 个人，返回长度为 people 的整数列表。

    约定：每个人拿到的金额之和，必须等于 amount_cents；任意两人相差不超过 1 分。
    """
    if amount_cents < 0:
        raise ValueError("amount_cents must be >= 0")
    if people <= 0:
        raise ValueError("people must be > 0")
    base, remainder = divmod(amount_cents, people)
    return [base + 1] * remainder + [base] * (people - remainder)
