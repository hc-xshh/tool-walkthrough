# ledger

账目月度报表：读 `data/*.csv`，按 `data/rates.json` 的汇率折成人民币，输出该月总额（分）。

```bash
python -m ledger.cli --month 2026-03 --data data
python -m unittest discover -s tests -v
```

公开 API（签名别改，别的模块和报表在用）：

- `parse.parse_timestamp(raw) -> date`
- `parse.read_entries(path) -> Iterator[Entry]`
- `fx.load_rates(path) -> dict`
- `fx.rate_for(rates, day, currency) -> float`
- `load.read_dir(data_dir) -> list[Entry]`
- `report.monthly_report(entries, month, rates) -> dict`
