"""命令行待办清单：add / list。

存储格式见 store.py：每条任务有 id / title / done / due 四个字段。
"""

import argparse
import sys

from store import load, next_id, save


def cmd_add(args):
    tasks = load(args.db)
    if any(t["title"] == args.title for t in tasks):
        print(f"已存在同名任务: {args.title}", file=sys.stderr)
        return 1
    task = {"id": next_id(tasks), "title": args.title, "done": False, "due": None}
    tasks.append(task)
    save(args.db, tasks)
    print(task["id"])
    return 0


def cmd_list(args):
    tasks = load(args.db)
    if not tasks:
        print("没有任务")
        return 0
    for t in tasks:
        mark = "[x]" if t["done"] else "[ ]"
        due = f" (due {t['due']})" if t.get("due") else ""
        print(f"{t['id']:>3} {mark} {t['title']}{due}")
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="todo")
    p.add_argument("--db", default="todo.json")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="新增任务")
    a.add_argument("title")
    a.add_argument("--due", help="截止日期，格式 YYYY-MM-DD")
    a.set_defaults(func=cmd_add)

    l = sub.add_parser("list", help="列出任务")
    l.set_defaults(func=cmd_list)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
