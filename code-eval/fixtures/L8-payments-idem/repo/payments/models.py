"""支付请求 / 结果。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ChargeRequest:
    request_id: str
    merchant: str
    amount: float  # 元
    currency: str = "CNY"
    created_at: float = 0.0  # epoch 秒


@dataclass(frozen=True)
class ChargeResult:
    request_id: str
    txn_id: str
    amount_cents: int
    status: str = "succeeded"

    def to_dict(self):
        return {
            "request_id": self.request_id,
            "txn_id": self.txn_id,
            "amount_cents": self.amount_cents,
            "status": self.status,
        }
