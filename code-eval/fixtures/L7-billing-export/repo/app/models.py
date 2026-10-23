"""订单模型：纯 dict，方便直接从 JSON 读进来。"""

STATUSES = ("paid", "pending", "void", "refunded")


def make_order(order_id, created_at, customer, amount, status="paid"):
    if status not in STATUSES:
        raise ValueError(f"unknown status: {status!r}")
    return {
        "id": order_id,
        "created_at": created_at,
        "customer": customer,
        "amount": float(amount),
        "status": status,
    }
