"""生成 L7 大仓库 fixture：一个百文件级的账单导出服务。

仓库里的真实文件（CLI、模型、导出器、测试、文档）手写在模板里；其余是
`app/plugins/plugin_XXX.py` 这类噪声模块——它们不参与导出，但名字和签名都很像，
用来考「在 100+ 文件里定位」而不是「读三个小文件」。

用法：python tools/make_large_fixture.py [--files 110]
"""

import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
REPO = EVAL / "fixtures" / "L7-billing-export" / "repo"

PLUGIN = '''"""插件 {index:03d}：{topic}。

{note}
"""

NAME = "plugin_{index:03d}"
TOPIC = "{topic}"


def run(payload, context=None):
    """把 payload 里的字段原样透传，补一个处理标记。"""
    context = context or {{}}
    out = dict(payload or {{}})
    out["handled_by"] = NAME
    out["topic"] = TOPIC
    return out
'''

TOPICS = [
    "订单补全", "客户去重", "地址清洗", "金额校验", "币种转换", "税率计算",
    "发票编号", "退款对账", "渠道映射", "物流状态", "批次归档", "缓存预热",
]
NOTES = [
    "不参与 CSV 导出，只在报表流水线上做字段补全。",
    "保留给旧版导出器调用，新代码不要依赖。",
    "只在批处理里跑，单条导出不会走到这里。",
    "历史遗留：字段名是拼音缩写，别按字面理解。",
]

REAL_FILES = {
    "app/__init__.py": '"""账单导出服务。"""\n\n__all__ = ["cli", "models", "exporters", "services", "handlers"]\n',
    "app/models.py": '''"""订单模型：纯 dict，方便直接从 JSON 读进来。"""

STATUSES = ("paid", "pending", "void", "refunded")


def make_order(order_id, created_at, customer, amount, status="paid"):
    if status not in STATUSES:
        raise ValueError(f"unknown status: {status!r}")
    return {
        "id": order_id,
        "created_at": created_at,
        "customer": customer,
        "amount": float(amount),
        "status": status,
    }
''',
    "app/exporters/__init__.py": '''"""导出器注册表：按格式找到实现。"""

from . import csv as _csv


def get_exporter(fmt):
    if fmt == "csv":
        return _csv.export_csv
    raise ValueError(f"unsupported format: {fmt!r}")
''',
    "app/exporters/csv.py": '''"""CSV 导出：财务每月从这份文件对账。"""

import csv

HEADER = ["id", "created_at", "customer", "amount", "status", "voided"]


def export_csv(orders, path):
    """把订单写成 CSV，金额保留两位小数。"""
    rows = [o for o in orders if o["status"] != "void"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER)
        for order in rows:
            writer.writerow([
                order["id"],
                order["created_at"],
                order["customer"],
                f"{order['amount']:.2f}",
                order["status"],
                "1" if order["status"] == "void" else "0",
            ])
''',
    "app/legacy/__init__.py": '"""旧版导出器，保留兼容。"""\n',
    "app/legacy/export_v1.py": '''"""v1：最早的导出，只在迁移脚本里用。"""


def export(orders, path):
    with open(path, "w", encoding="utf-8") as fh:
        for order in orders:
            if order["status"] == "void":
                continue
            fh.write(f"{order['id']},{order['amount']}\\n")
''',
    "app/legacy/export_v2.py": '''"""v2：加了状态过滤，但仍不进财务口径。"""

import csv

HEADER = ["id", "amount", "status"]


def export(orders, path):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER)
        for order in orders:
            if order["status"] in ("void", "cancelled"):
                continue
            writer.writerow([order["id"], f"{order['amount']:.2f}", order["status"]])
''',
    "app/services/__init__.py": '"""服务层。"""\n',
    "app/services/orders.py": '''"""订单查询：从 JSON 读、按月份筛。"""

import json
from pathlib import Path


def load_orders(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def by_month(orders, month):
    return [o for o in orders if o["created_at"].startswith(month)]
''',
    "app/services/refunds.py": '''"""退款：只改状态，不删订单。"""


def refund(orders, order_id):
    for order in orders:
        if order["id"] == order_id:
            order["status"] = "refunded"
            return order
    raise KeyError(order_id)
''',
    "app/utils/__init__.py": '"""工具函数。"""\n',
    "app/utils/money.py": '''"""金额：一律用分做内部计算。"""


def to_cents(amount):
    return int(round(float(amount) * 100))


def from_cents(cents):
    return cents / 100.0
''',
    "app/utils/dates.py": '''"""日期：只认 YYYY-MM-DD。"""

from datetime import date


def month_of(iso_date):
    return iso_date[:7]


def parse_day(iso_date):
    return date.fromisoformat(iso_date)
''',
    "app/handlers/__init__.py": '"""任务入口（HTTP / 定时）。"""\n',
    "app/handlers/jobs.py": '''"""定时任务：每月导出一次对账单。"""

from app.exporters import get_exporter


def monthly_export(orders, path, fmt="csv"):
    exporter = get_exporter(fmt)
    exporter(orders, path)
    return len(orders)
''',
    "app/cli.py": '''"""命令行：python -m app.cli export --in orders.json --out out.csv"""

import argparse
import sys

from app.exporters import get_exporter
from app.services.orders import load_orders


def build_parser():
    p = argparse.ArgumentParser(prog="billing")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export", help="导出订单")
    e.add_argument("--in", dest="src", required=True)
    e.add_argument("--out", dest="dst", required=True)
    e.add_argument("--format", default="csv")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    orders = load_orders(args.src)
    exporter = get_exporter(args.format)
    exporter(orders, args.dst)
    print(f"exported {len(orders)} orders -> {args.dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
''',
    "tests/test_export.py": '''import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ExportTest(unittest.TestCase):
    def test_exports_paid_orders(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "orders.json"
            dst = tmp / "out.csv"
            src.write_text(
                json.dumps(
                    [
                        {"id": "o1", "created_at": "2026-03-01", "customer": "甲", "amount": 12.3, "status": "paid"},
                        {"id": "o2", "created_at": "2026-03-02", "customer": "乙", "amount": 5, "status": "pending"},
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            res = subprocess.run(
                [sys.executable, "-m", "app.cli", "export", "--in", str(src), "--out", str(dst)],
                cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(res.returncode, 0, res.stderr)
            rows = list(csv.reader(dst.read_text(encoding="utf-8").splitlines()))
        self.assertEqual(rows[0], ["id", "created_at", "customer", "amount", "status", "voided"])
        self.assertEqual([r[0] for r in rows[1:]], ["o1", "o2"])
        self.assertEqual(rows[1][3], "12.30")


if __name__ == "__main__":
    unittest.main()
''',
    "README.md": '''# billing-export

账单导出服务。财务每月跑一次：

```bash
python -m app.cli export --in data/orders.json --out out.csv
python -m unittest discover -s tests -v
```

`app/exporters/` 下每个格式一个模块，`app/legacy/` 是旧版导出（不要动）。
''',
    "data/orders.json": '''[
  {"id": "o1", "created_at": "2026-03-01", "customer": "甲公司", "amount": 1280.5, "status": "paid"},
  {"id": "o2", "created_at": "2026-03-04", "customer": "乙公司", "amount": 300, "status": "pending"},
  {"id": "o3", "created_at": "2026-03-09", "customer": "丙公司", "amount": 88.88, "status": "void"}
]
''',
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", type=int, default=110, help="噪声插件数量")
    a = ap.parse_args()

    for rel, text in REAL_FILES.items():
        path = REPO / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    for index in range(1, a.files + 1):
        topic = TOPICS[index % len(TOPICS)]
        note = NOTES[index % len(NOTES)]
        path = REPO / "app" / "plugins" / f"plugin_{index:03d}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            PLUGIN.format(index=index, topic=topic, note=note).replace("{{", "{").replace("}}", "}"),
            encoding="utf-8",
        )

    (REPO / "app" / "plugins" / "__init__.py").write_text(
        '"""插件目录：只在报表流水线里用，导出不会走到这里。"""\n', encoding="utf-8"
    )

    total = sum(1 for _ in REPO.rglob("*.py"))
    print(f"repo: {REPO}")
    print(f"python files: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
