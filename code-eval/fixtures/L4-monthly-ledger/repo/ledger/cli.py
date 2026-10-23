"""命令行入口：python -m ledger.cli --month 2026-03 --data data"""

import argparse
import json
import sys

from .fx import load_rates
from .load import read_dir
from .report import monthly_report


def build_parser():
    p = argparse.ArgumentParser(prog="ledger")
    p.add_argument("--month", required=True, help="YYYY-MM")
    p.add_argument("--data", default="data")
    p.add_argument("--rates", default="data/rates.json")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    report = monthly_report(read_dir(args.data), args.month, load_rates(args.rates))
    print(
        json.dumps(
            {
                "month": report["month"],
                "count": report["count"],
                "total_cents": report["total_cents"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
