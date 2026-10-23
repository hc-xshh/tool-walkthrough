"""文件树快照与改动对比。

不依赖 git：agent 可能留下半套改动、可能删文件、可能改二进制，这里按内容哈希
记录，再对比出新增 / 修改 / 删除。git 只作为证据补充（patch 文本）。

用法：
  python tools/snap.py take <root> <out.json>
  python tools/snap.py diff <before.json> <root>
"""

import difflib
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

SKIP_DIRS = {"__pycache__", ".git", ".venv", ".pytest_cache", "_accept", ".mypy_cache"}
SKIP_SUFFIX = {".pyc", ".pyo"}
MAX_DIFF_BYTES = 200_000


def find_git():
    """PATH 里没有时去常见安装位置找——长驻进程的环境变量经常是旧的。"""
    found = shutil.which("git")
    if found:
        return found
    for candidate in (
        r"C:\Program Files\Git\cmd\git.exe",
        "/usr/bin/git",
        "/usr/local/bin/git",
        "/opt/homebrew/bin/git",
    ):
        if Path(candidate).exists():
            return candidate
    return None


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def file_set(root):
    """相对路径 -> sha256。忽略解释器缓存与判分时临时挂载的验收目录。"""
    root = Path(root).resolve()
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if p.suffix in SKIP_SUFFIX:
                continue
            out[p.relative_to(root).as_posix()] = sha256(p)
    return out


def diff_sets(before, after):
    added = sorted(set(after) - set(before))
    deleted = sorted(set(before) - set(after))
    modified = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    return {"added": added, "modified": modified, "deleted": deleted}


def text_lines(path):
    p = Path(path)
    try:
        if p.stat().st_size > MAX_DIFF_BYTES:
            return None
        return p.read_text(encoding="utf-8").splitlines(keepends=True)
    except (UnicodeDecodeError, OSError):
        return None


def unified_diff(before_root, after_root, rel):
    a = text_lines(Path(before_root) / rel)
    b = text_lines(Path(after_root) / rel)
    if a is None or b is None:
        return f"--- {rel} (binary or too large)\n"
    return "".join(
        difflib.unified_diff(a, b, fromfile=f"a/{rel}", tofile=f"b/{rel}")
    )


def line_counts(text):
    added = sum(1 for ln in text.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in text.splitlines() if ln.startswith("-") and not ln.startswith("---"))
    return added, removed


def take(root, out_path):
    data = {"root": str(Path(root).resolve()), "files": file_set(root)}
    Path(out_path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def diff(before_path, after_root):
    before = json.loads(Path(before_path).read_text(encoding="utf-8"))
    after = file_set(after_root)
    changes = diff_sets(before["files"], after)
    patch_parts = []
    for rel in changes["modified"]:
        patch_parts.append(unified_diff(before["root"], after_root, rel))
    for rel in changes["added"]:
        lines = text_lines(Path(after_root) / rel)
        if lines is not None:
            patch_parts.append(
                "".join(difflib.unified_diff([], lines, fromfile="/dev/null", tofile=f"b/{rel}"))
            )
    for rel in changes["deleted"]:
        lines = text_lines(Path(before["root"]) / rel)
        if lines is not None:
            patch_parts.append(
                "".join(difflib.unified_diff(lines, [], fromfile=f"a/{rel}", tofile="/dev/null"))
            )
    patch = "".join(patch_parts)
    added, removed = line_counts(patch)
    changes["lines_added"] = added
    changes["lines_removed"] = removed
    changes["patch"] = patch
    return changes


def main(argv):
    if len(argv) != 4 or argv[1] not in ("take", "diff"):
        print(__doc__)
        return 2
    if argv[1] == "take":
        take(argv[2], argv[3])
        print(f"snapshot {argv[2]} -> {argv[3]}")
        return 0
    print(json.dumps(diff(argv[2], argv[3]), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
