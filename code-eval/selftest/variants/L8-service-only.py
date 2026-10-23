"""负例：金额换成 money.to_cents，但幂等键没修。"""

from . import keys, money
from .gateway import GatewayTimeout
from .models import ChargeResult


def charge(request, store, gateway, now):
    key = keys.build_key(request, now)

    cached = store.get(key, now)
    if cached is not None:
        return cached

    amount_cents = money.to_cents(request.amount)
    last_error = None
    for attempt in range(2):
        try:
            txn_id = gateway.charge(key, amount_cents)
            result = ChargeResult(
                request_id=request.request_id,
                txn_id=txn_id,
                amount_cents=amount_cents,
            )
            store.put(key, result, now)
            return result
        except GatewayTimeout as exc:
            last_error = exc
            key = keys.build_key(request, now + attempt + 1)
            cached = store.get(key, now)
            if cached is not None:
                return cached

    raise last_error
