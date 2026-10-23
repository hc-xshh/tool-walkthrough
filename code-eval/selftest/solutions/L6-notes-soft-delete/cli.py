"""命令行入口：

    python -m notes.cli sync --store notes.json --tombstones tombstones.json --feed feed.json
    python -m notes.cli list --store notes.json [--include-deleted]
"""

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

    l = sub.add_parser("list", help="列出账本")
    l.add_argument("--store", default="notes.json")
    l.add_argument("--include-deleted", action="store_true")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.cmd == "list":
        notes = load_notes(args.store)
        if not args.include_deleted:
            notes = [n for n in notes if not n.get("deleted_at")]
        print(json.dumps(notes, ensure_ascii=False))
        return 0

    notes = load_notes(args.store)
    tombstones = load_tombstones(args.tombstones)

    try:
        batch = json.loads(Path(args.feed).read_text(encoding="utf-8"))
        notes, tombstones, stats = apply_batch(notes, tombstones, batch)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    save_notes(args.store, notes)
    save_tombstones(args.tombstones, tombstones)
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
