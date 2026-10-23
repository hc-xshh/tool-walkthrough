"""支付网关客户端。

网关支持幂等键：同一个 key 重复扣款只会产生一笔交易，返回同一个 txn_id。
"""


class GatewayTimeout(Exception):
    """网关超时：扣款可能已经发生，也可能没有。"""


class Gateway:
    def __init__(self, timeout_once=False):
        self.timeout_once = timeout_once
        self.calls = 0
        self.charges = []  # 实际产生的交易
        self._by_key = {}

    def charge(self, key, amount_cents):
        self.calls += 1
        if key in self._by_key:
            return self._by_key[key]
        if self.timeout_once:
            self.timeout_once = False
            # 扣款已经发生，只是响应丢了
            txn_id = f"txn-{len(self.charges) + 1:04d}"
            self.charges.append({"key": key, "amount_cents": amount_cents, "txn_id": txn_id})
            self._by_key[key] = txn_id
            raise GatewayTimeout("response lost")
        txn_id = f"txn-{len(self.charges) + 1:04d}"
        self.charges.append({"key": key, "amount_cents": amount_cents, "txn_id": txn_id})
        self._by_key[key] = txn_id
        return txn_id
