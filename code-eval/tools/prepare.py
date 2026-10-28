"""准备一次尝试：复制 fixture 到工作目录、打 baseline 提交、记录改动前快照。

用法：
  python tools/prepare.py --task L1-split-bill --workdir runs/x/work/L1-r1 [--force]

工作目录必须由调用方指定（一般在 runs/ 下，已被 .gitignore 忽略）。快照写在
工作目录旁边：<workdir>.before.json，agent 看不到也改不到。
"""

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL_ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import snap  # noqa: E402


def force_remove(func, path, exc):
    """git 的对象文件是只读的，Windows 上 rmtree 会 PermissionError。"""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def rmtree(path):
    """shutil.rmtree 的跨版本包装：3.12+ 用 onexc，3.9–3.11 只有 onerror。"""
    try:
        shutil.rmtree(path, onexc=force_remove)
    except TypeError:
        shutil.rmtree(path, onerror=lambda func, p, exc_info: force_remove(func, p, exc_info))


def git(args, cwd):
    git_bin = snap.find_git()
    if not git_bin:
        return None
    p = subprocess.run(
        [git_bin, *args], cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if p.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {p.stderr.strip()}")
    return p.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    spec = json.loads((EVAL_ROOT / "tasks" / f"{a.task}.json").read_text(encoding="utf-8"))
    src = EVAL_ROOT / spec["fixture"]
    workdir = Path(a.workdir).resolve()
    before = workdir.parent / (workdir.name + ".before.json")
    meta = workdir.parent / (workdir.name + ".meta.json")

    if workdir.exists():
        if not a.force:
            raise SystemExit(f"{workdir} already exists; pass --force to rebuild")
        rmtree(workdir)
    workdir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, workdir)

    # 有些 fixture 依赖构建时生成的文件（setuptools_scm 的 _version.py 之类），
    # 这些文件在被 vendor 的仓库自己的 .gitignore 里，clone 下来必然缺失。
    # 由任务规格声明内容，prepare 时写进工作副本——不要靠本机残留文件。
    for rel, content in (spec.get("generated") or {}).items():
        target = workdir / rel
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    baseline = None
    if snap.find_git():
        git(["init", "-q"], workdir)
        git(["add", "-A"], workdir)
        git(["-c", "user.name=code-eval", "-c", "user.email=eval@local",
             "commit", "-qm", "baseline"], workdir)
        baseline = git(["rev-parse", "--short", "HEAD"], workdir).strip()

    snap.take(workdir, before)
    meta.write_text(
        json.dumps(
            {
                "task": spec["id"],
                "level": spec.get("level"),
                "fixture": str(src),
                "baseline": baseline,
                "prompts": [
                    str(EVAL_ROOT / rel)
                    for rel in (spec.get("prompts") or [spec["prompt"]])
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"workdir": str(workdir), "before": str(before),
                      "baseline": baseline}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
