# billing-export

账单导出服务。财务每月跑一次：

```bash
python -m app.cli export --in data/orders.json --out out.csv
python -m unittest discover -s tests -v
```

`app/exporters/` 下每个格式一个模块，`app/legacy/` 是旧版导出（不要动）。
