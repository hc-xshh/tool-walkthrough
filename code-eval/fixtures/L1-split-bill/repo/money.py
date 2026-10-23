"""账单拆分工具：把一笔金额按人数拆成整数分。"""


def split_bill(amount_cents, people):
    """把 amount_cents（分）平均拆给 people 个人，返回长度为 people 的整数列表。

    约定：每个人拿到的金额之和，必须等于 amount_cents。
    """
    each = amount_cents // people
    return [each] * people
