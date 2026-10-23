"""JSON 存储：notes 是一个数组，一条一个对象。"""

import json
from pathlib import Path


def load_notes(path):
    p = Path(path)
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def save_notes(path, notes):
    Path(path).write_text(
        json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_tombstones(path):
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def save_tombstones(path, tombstones):
    Path(path).write_text(
        json.dumps(tombstones, ensure_ascii=False, indent=2), encoding="utf-8"
    )
