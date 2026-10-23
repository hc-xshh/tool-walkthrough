"""用 CDP 驱动 TRAE 的 Agent 窗口跑一次任务，然后交给 grade.py 判分。

流程：新建任务 → 等编辑区可点 → 清空 → 插入任务书（校验插入成功）→ 回车
→ 轮询（自动点「本次会话允许」）→ 判分。任务书里的 {workdir} 会替换成本次工作目录。

用法：
  python tools/drive_trae.py --task L1-split-bill --workdir runs/x/work/L1-r1 \\
      --rep 1 --out runs/x/results/L1-r1.json [--prepare] [--timebox 600] [--debug]
"""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
REPO = EVAL.parent
CDP = [sys.executable, str(REPO / "harness" / "cdp.py"), "--match", "solo-lite"]
EDITOR = ".chat-input-v2-input-box-editable"
TMP_JS = HERE / "_drive_tmp.js"


def cdp(op, arg=None, timeout=90, check=False):
    cmd = CDP + [op] + ([arg] if arg else [])
    p = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout,
    )
    if check and p.returncode != 0:
        raise RuntimeError(f"cdp {op} failed: {(p.stdout + p.stderr)[-600:]}")
    return p


def js_eval(source, timeout=60):
    TMP_JS.write_text(source, encoding="utf-8")
    try:
        p = cdp("eval", "@" + str(TMP_JS), timeout=timeout)
    finally:
        TMP_JS.unlink(missing_ok=True)
    if p.returncode != 0:
        return None
    raw = p.stdout.strip()
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def page_text():
    p = cdp("text")
    return p.stdout if p.returncode == 0 else ""


def log(path, event, **fields):
    rec = {"ts": time.strftime("%H:%M:%S"), "event": event, **fields}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def editor_info():
    return js_eval(
        f"""(() => {{
          const el = document.querySelector('{EDITOR}');
          if (!el) return null;
          return {{text: el.innerText, len: (el.innerText || '').length}};
        }})()"""
    )


def editor_rect():
    """编辑区中心点；被浮层盖住时返回 '__covered__'。"""
    return js_eval(
        f"""(() => {{
          const el = document.querySelector('{EDITOR}');
          if (!el) return null;
          const r = el.getBoundingClientRect();
          if (r.width < 120 || r.height < 16) return null;
          const cx = r.x + r.width / 2, cy = r.y + r.height / 2;
          const hit = document.elementFromPoint(cx, cy);
          if (!(hit === el || el.contains(hit))) return '__covered__';
          return {{x: Math.round(cx), y: Math.round(cy)}};
        }})()"""
    )


def click_editor(log_path, tries=12):
    for _ in range(tries):
        pos = editor_rect()
        if pos == "__covered__":
            cdp("key", "Escape")
            time.sleep(0.8)
            continue
        if isinstance(pos, dict):
            cdp("clickxy", f"{pos['x']},{pos['y']}")
            time.sleep(0.4)
            return True
        time.sleep(0.8)
    return False


def clear_editor():
    cdp("keycombo", "ctrl+a")
    cdp("key", "Backspace")
    time.sleep(0.3)


def click_label(label, nth=None):
    cmd = ["clickel", label] + (["--nth", str(nth)] if nth is not None else [])
    return cdp(*cmd, timeout=60).returncode == 0


def approve(log_path):
    for label in ("本次会话允许", "仅本次运行"):
        if click_label(label):
            log(log_path, "approve", label=label)
            return True
    return False


def wait_done(log_path, timebox, debug=False, idle_s=45):
    """完成信号：出现「任务耗时」，或界面 idle_s 秒没有变化。

    不用侧栏的「任务完成」计数：上一轮任务恰好在此刻结束时会误触发。
    """
    deadline = time.time() + timebox
    approvals = 0
    last = ""
    last_change = time.time()
    while time.time() < deadline:
        current = page_text()
        if current != last:
            tail = current.strip()[-260:].replace("\n", " | ")
            log(log_path, "state", tail=tail)
            if debug:
                print("STATE:", tail)
            last, last_change = current, time.time()
        if "本次会话允许" in current:
            if approve(log_path):
                approvals += 1
                time.sleep(2)
                continue
        if "任务耗时" in current and "本次会话允许" not in current:
            log(log_path, "done", approvals=approvals, marker="elapsed")
            return True, approvals, last_change
        if time.time() - last_change > idle_s:
            log(log_path, "done", approvals=approvals, marker=f"idle{idle_s}")
            return True, approvals, last_change
        time.sleep(2)
    log(log_path, "timeout", approvals=approvals)
    return False, approvals, last_change


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--out", required=True)
    ap.add_argument("--before", default=None)
    ap.add_argument("--timebox", type=int, default=900)
    ap.add_argument("--tool", default="TRAE CN 3.4.4 / Agent / deepseek-v4-flash")
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--idle", type=int, default=45,
                    help="界面多久没变化就算任务结束（秒）")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    workdir = Path(a.workdir).resolve()
    spec = json.loads((EVAL / "tasks" / f"{a.task}.json").read_text(encoding="utf-8"))
    prompt = (EVAL / spec["prompt"]).read_text(encoding="utf-8").replace(
        "{workdir}", str(workdir)
    )

    log_path = Path(a.out).parent / (Path(a.out).stem + ".trace.jsonl")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")

    if a.prepare:
        prep_cmd = [sys.executable, str(HERE / "prepare.py"), "--task", a.task,
                    "--workdir", str(workdir)]
        if a.force:
            prep_cmd.append("--force")
        p = subprocess.run(prep_cmd, capture_output=True, text=True, encoding="utf-8")
        if p.returncode != 0:
            raise SystemExit(f"prepare failed: {p.stderr}")
        print(p.stdout.strip())

    before = Path(a.before) if a.before else workdir.parent / (workdir.name + ".before.json")

    if a.dry_run:
        print(prompt)
        return 0

    log(log_path, "start", task=a.task, rep=a.rep, workdir=str(workdir))
    click_label("新建任务")
    time.sleep(2)

    if not click_editor(log_path):
        raise SystemExit("editor not clickable (covered or missing)")
    clear_editor()
    state = editor_info()
    if not state or state["len"] > 1:  # 空编辑区是一个换行
        raise SystemExit(f"editor not empty before typing: {state}")

    cdp("type", prompt, check=True)
    time.sleep(0.6)
    state = editor_info()
    if not state or state["len"] < 80:
        # 有时第一次插入落在错误焦点上，重试一次
        if not click_editor(log_path):
            raise SystemExit("editor lost before retry")
        clear_editor()
        cdp("type", prompt, check=True)
        time.sleep(0.6)
        state = editor_info()
    if not state or state["len"] < 80:
        raise SystemExit(f"prompt not inserted: {state}")
    log(log_path, "typed", chars=state["len"])

    cdp("key", "Enter", check=True)
    started = time.time()
    time.sleep(1.5)
    after = editor_info()
    if after and after["len"] >= 80 and state["len"] >= 80 and after["text"] == state["text"]:
        # 回车没提交：试发送按钮
        for label in ("发送", "Send"):
            if click_label(label):
                log(log_path, "send-button", label=label)
                break
    log(log_path, "submit")

    ok, approvals, last_change = wait_done(
        log_path, a.timebox, a.debug, a.idle
    )
    took = round(time.time() - started, 1)
    measured = round(last_change - started, 1) if last_change else took
    text = page_text()
    m = [int(x) for x in re.findall(r"任务耗时\s*(\d+)", text)]
    ui_elapsed = m[-1] if m else None
    try:
        cdp("shot", str(Path(a.out).with_suffix(".png")))
    except Exception:
        pass

    grade_cmd = [
        sys.executable, str(HERE / "grade.py"),
        "--task", a.task, "--workdir", str(workdir), "--before", str(before),
        "--out", a.out, "--rep", str(a.rep), "--tool", a.tool,
        "--duration", str(ui_elapsed or measured), "--interventions", str(approvals),
    ]
    g = subprocess.run(grade_cmd, capture_output=True, text=True, encoding="utf-8")
    print((g.stdout or "").strip())
    if g.returncode != 0 and "result ->" not in (g.stdout or ""):
        print((g.stderr or "")[-800:], file=sys.stderr)
    log(log_path, "graded", finished=ok, approvals=approvals,
        wall_s=took, measured_s=measured, ui_elapsed=ui_elapsed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
