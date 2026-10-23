# payments

扣款服务：客户端带 `request_id`，服务端保证同一 `request_id` 只扣一次、返回同一个 `txn_id`。

```bash
python -m unittest discover -s tests -v
```

分层：

- `payments/api.py` —— 对外入口：`handle_charge(payload, store, gateway, now)`
- `payments/service.py` —— 扣款流程与重试
- `payments/keys.py` —— 幂等键
- `payments/store.py` —— 幂等存储（TTL）
- `payments/gateway.py` —— 网关客户端（支持幂等键，超时会抛 `GatewayTimeout`）
- `payments/money.py` —— 元 / 分换算

`payments/adapters/` 下是其它渠道的适配器，和本流程无关。
