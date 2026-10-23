"""命令行：python -m app.cli export --in orders.json --out out.csv"""

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
