"""扣款服务：先查幂等存储，再调网关；超时重试。"""

from . import keys
from .gateway import GatewayTimeout
from .models import ChargeResult


def charge(request, store, gateway, now):
    key = keys.build_key(request, now)

    cached = store.get(key, now)
    if cached is not None:
        return cached

    last_error = None
    for attempt in range(2):
        try:
            txn_id = gateway.charge(key, int(request.amount * 100))
            result = ChargeResult(
                request_id=request.request_id,
                txn_id=txn_id,
                amount_cents=int(request.amount * 100),
            )
            store.put(key, result, now)
            return result
        except GatewayTimeout as exc:
            last_error = exc
            # 超时后换一个新的键重试，避免命中上一次的失败记录
            key = keys.build_key(request, now + attempt + 1)
            cached = store.get(key, now)
            if cached is not None:
                return cached

    raise last_error
