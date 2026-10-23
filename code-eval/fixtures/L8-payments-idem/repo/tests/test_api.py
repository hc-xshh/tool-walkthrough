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


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.store = IdempotencyStore()
        self.gateway = Gateway()

    def test_single_charge(self):
        out = handle_charge(payload(), self.store, self.gateway, now=1000.0)
        self.assertEqual(out["amount_cents"], 10000)
        self.assertEqual(out["txn_id"], "txn-0001")
        self.assertEqual(self.gateway.calls, 1)


if __name__ == "__main__":
    unittest.main()
