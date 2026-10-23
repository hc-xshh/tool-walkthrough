"""L8 隐藏验收：跨文件一致性（幂等键、金额换算、超时重试）。"""

import unittest

from payments.api import handle_charge
from payments.gateway import Gateway
from payments.store import IdempotencyStore


def payload(request_id="r-1", amount=100.0, created_at=1000.0):
    return {
        "request_id": request_id,
        "merchant": "m-1",
        "amount": amount,
        "currency": "CNY",
        "created_at": created_at,
    }


class IdempotencyAccept(unittest.TestCase):
    def setUp(self):
        self.gateway = Gateway()
        self.store = IdempotencyStore()

    def test_duplicate_request_charges_once(self):
        first = handle_charge(payload(), self.store, self.gateway, now=1000.0)
        second = handle_charge(payload(), self.store, self.gateway, now=1030.0)
        self.assertEqual(first, second, "同一 request_id 的返回不一致")
        self.assertEqual(self.gateway.calls, 1, "重复请求打到了网关")
        self.assertEqual(len(self.gateway.charges), 1, "同一请求扣了两次钱")

    def test_late_retry_after_created_at_is_still_same_request(self):
        handle_charge(payload(created_at=1000.0), self.store, self.gateway, now=1000.0)
        again = handle_charge(payload(created_at=1000.0), self.store, self.gateway, now=9000.0)
        self.assertEqual(again["txn_id"], "txn-0001")
        self.assertEqual(len(self.gateway.charges), 1)

    def test_timeout_retries_with_same_key_and_charges_once(self):
        timeout_gateway = Gateway(timeout_once=True)
        out = handle_charge(payload(), self.store, timeout_gateway, now=1000.0)
        self.assertEqual(len(timeout_gateway.charges), 1, "超时重试产生了第二笔扣款")
        self.assertEqual(out["txn_id"], "txn-0001")
        self.assertEqual(timeout_gateway.calls, 2, "应该用同一个键重试一次")

    def test_amount_uses_half_up_cents(self):
        out = handle_charge(payload(amount=19.99), self.store, self.gateway, now=1000.0)
        self.assertEqual(out["amount_cents"], 1999)
        self.assertEqual(self.gateway.charges[0]["amount_cents"], 1999)

    def test_different_requests_charge_separately(self):
        handle_charge(payload("r-1"), self.store, self.gateway, now=1000.0)
        handle_charge(payload("r-2"), self.store, self.gateway, now=1000.0)
        self.assertEqual(len(self.gateway.charges), 2)
        self.assertEqual(self.gateway.charges[1]["txn_id"], "txn-0002")

    def test_replay_returns_the_stored_payload(self):
        first = handle_charge(payload(amount=19.99), self.store, self.gateway, now=1000.0)
        replay = handle_charge(payload(amount=19.99), self.store, self.gateway, now=5000.0)
        self.assertEqual(replay, first)
        self.assertEqual(set(replay), {"request_id", "txn_id", "amount_cents", "status"})


if __name__ == "__main__":
    unittest.main()
