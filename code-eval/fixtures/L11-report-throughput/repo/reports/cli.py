"""报表 CLI：python -m reports.cli --input ... --rates ... --out ..."""

import argparse
import json
import sys

from .aggregate import aggregate, load_orders, load_rates


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--rates", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    try:
        result = aggregate(load_orders(a.input), load_rates(a.rates))
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, sort_keys=True)
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
