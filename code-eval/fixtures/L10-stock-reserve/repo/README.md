# 库存预占服务

HTTP 库存服务，数据在 `data/stock.json`。

```bash
python -m unittest discover -s tests -v
python app.py --port 8000 --data data
```

接口：

- `POST /reserve` `{"sku": "...", "qty": 1, "request_id": "..."}`
- `GET /stock/<sku>`
