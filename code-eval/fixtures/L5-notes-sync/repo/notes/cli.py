"""命令行入口：python -m notes.cli sync --store notes.json --feed feed.json"""

import argparse
import json
import sys
from pathlib import Path

from .store import load_notes, load_tombstones, save_notes, save_tombstones
from .sync import apply_batch

DEFAULT_TOMBSTONES = "tombstones.json"


def build_parser():
    p = argparse.ArgumentParser(prog="notes")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync", help="应用一份增量 feed")
    s.add_argument("--store", default="notes.json")
    s.add_argument("--tombstones", default=DEFAULT_TOMBSTONES)
    s.add_argument("--feed", required=True)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    notes = load_notes(args.store)
    tombstones = load_tombstones(args.tombstones)
    batch = json.loads(Path(args.feed).read_text(encoding="utf-8"))

    notes, tombstones, stats = apply_batch(notes, tombstones, batch)
    save_notes(args.store, notes)
    save_tombstones(args.tombstones, tombstones)
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
