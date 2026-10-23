"""命令行待办清单：add / list / done。

存储格式见 store.py：每条任务有 id / title / done / due 四个字段。
"""

import argparse
import sys
from datetime import date

from store import load, next_id, save


def parse_due(text):
    if not text:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise ValueError(f"日期格式应为 YYYY-MM-DD: {text}")


def cmd_add(args):
    tasks = load(args.db)
    if any(t["title"] == args.title for t in tasks):
        print(f"已存在同名任务: {args.title}", file=sys.stderr)
        return 1
    try:
        due = parse_due(args.due)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    task = {"id": next_id(tasks), "title": args.title, "done": False, "due": due}
    tasks.append(task)
    save(args.db, tasks)
    print(task["id"])
    return 0


def cmd_list(args):
    tasks = load(args.db)
    if args.due is not None:
        try:
            due = parse_due(args.due)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 2
        tasks = [t for t in tasks if t.get("due") == due]
    if not tasks:
        print("没有任务")
        return 0
    for t in tasks:
        mark = "[x]" if t["done"] else "[ ]"
        due = f" (due {t['due']})" if t.get("due") else ""
        print(f"{t['id']:>3} {mark} {t['title']}{due}")
    return 0


def cmd_done(args):
    tasks = load(args.db)
    for t in tasks:
        if t["id"] == args.id:
            t["done"] = True
            save(args.db, tasks)
            print(args.id)
            return 0
    print(f"没有 id 为 {args.id} 的任务", file=sys.stderr)
    return 1


def build_parser():
    p = argparse.ArgumentParser(prog="todo")
    p.add_argument("--db", default="todo.json")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="新增任务")
    a.add_argument("title")
    a.add_argument("--due", help="截止日期，格式 YYYY-MM-DD")
    a.set_defaults(func=cmd_add)

    l = sub.add_parser("list", help="列出任务")
    l.add_argument("--due", help="只看这个日期的任务")
    l.set_defaults(func=cmd_list)

    d = sub.add_parser("done", help="标记完成")
    d.add_argument("id", type=int)
    d.set_defaults(func=cmd_done)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
