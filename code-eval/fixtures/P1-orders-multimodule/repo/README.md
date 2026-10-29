# 订单服务（基线）

一个很小的订单服务，用来演示跨模块改动：

```
python app.py --port 8787 --data data
python -m unittest discover -s tests -v
```

现有接口：

- `GET /health`
- `GET /orders`
- `GET /orders/<id>`
- `GET /inventory/<sku>`
- `GET /reports/daily?date=YYYY-MM-DD`
- `GET /audit?order_id=<id>`

数据在 `data/shop.db`（旧结构，没有 `cancelled_at`）。
