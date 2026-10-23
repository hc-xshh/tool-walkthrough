"""JSON 文件存储：任务列表的读写。"""

import json
from pathlib import Path


def load(path):
    p = Path(path)
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    return [normalize(t) for t in data]


def normalize(task):
    return {
        "id": int(task["id"]),
        "title": str(task.get("title", "")),
        "done": bool(task.get("done", False)),
        "due": task.get("due"),
    }


def save(path, tasks):
    Path(path).write_text(
        json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def next_id(tasks):
    return max([t["id"] for t in tasks], default=0) + 1
