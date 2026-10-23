"""退款：只改状态，不删订单。"""


def refund(orders, order_id):
    for order in orders:
        if order["id"] == order_id:
            order["status"] = "refunded"
            return order
    raise KeyError(order_id)
