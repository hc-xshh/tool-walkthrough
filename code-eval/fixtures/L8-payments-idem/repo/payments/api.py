"""对外接口：校验请求、调服务、核对金额。"""

from . import money
from .models import ChargeRequest
from .service import charge as _charge


class AmountMismatch(Exception):
    """扣款金额与请求金额对不上。"""


def handle_charge(payload, store, gateway, now):
    request = ChargeRequest(**payload)
    result = _charge(request, store, gateway, now)

    expected = money.to_cents(request.amount)
    if result.amount_cents != expected:
        raise AmountMismatch(
            f"amount mismatch: charged {result.amount_cents}, expected {expected}"
        )
    return result.to_dict()
