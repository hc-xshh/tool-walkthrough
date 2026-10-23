"""用 CDP 驱动 TRAE 的 Agent 窗口跑一次任务，然后交给 grade.py 判分。

流程：新建任务 → 等编辑区可点 → 清空 → 插入任务书（校验插入成功）→ 回车
→ 轮询（自动点「本次会话允许」）→ 判分。任务书里的 {workdir} 会替换成本次工作目录。

用法：
  python tools/drive_trae.py --task L1-split-bill --workdir runs/x/work/L1-r1 \\
      --rep 1 --out runs/x/results/L1-r1.json [--prepare] [--timebox 600] [--debug]
"""

import argparse
import json
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
APPROVE_LABELS = ("本次会话允许", "本次会话", "仅本次运行", "运行", "允许")


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
    """编辑区中心点；被浮层盖住时返回 '__covered__'，不在视口内先滚进来。"""
    return js_eval(
        f"""(() => {{
          const el = document.querySelector('{EDITOR}');
          if (!el) return null;
          let r = el.getBoundingClientRect();
          if (r.top < 60 || r.bottom > window.innerHeight - 30) {{
            el.scrollIntoView({{block: 'center'}});
            r = el.getBoundingClientRect();
          }}
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
            label = pending_approval()
            if label and click_label(label):
                time.sleep(1.5)
                continue
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


def pending_approval():
    """当前页面是否有一个可点的授权按钮，返回它的文案。"""
    labels = json.dumps(list(APPROVE_LABELS), ensure_ascii=False)
    return js_eval(
        f"""(() => {{
          const labels = {labels};
          const els = Array.from(document.querySelectorAll('button,[role="button"],div,span'))
            .filter(e => e.offsetParent !== null);
          for (const label of labels) {{
            if (els.some(e => (e.innerText || '').trim() === label)) return label;
          }}
          return null;
        }})()"""
    )


def approve(log_path):
    label = pending_approval()
    if not label:
        return False
    if click_label(label):
        log(log_path, "approve", label=label)
        return True
    return False


def wait_done(log_path, timebox, debug=False, idle_s=45):
    """完成信号：界面 idle_s 秒没有变化。

    不用「任务耗时」：上一轮结束时的这句话会一直留在页面里，多轮任务会立刻误判。
    也不用侧栏「任务完成」计数：上一轮收尾时会误触发。
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
        label = pending_approval()
        if label and click_label(label):
            approvals += 1
            log(log_path, "approve", label=label)
            time.sleep(2)
            continue
        if time.time() - last_change > idle_s:
            log(log_path, "done", approvals=approvals, marker=f"idle{idle_s}")
            return True, approvals, last_change
        time.sleep(2)
    log(log_path, "timeout", approvals=approvals)
    return False, approvals, last_change


def build_feedback(result):
    """把上一轮的隐藏验收失败摘要变成下一轮的 prompt（不给测试源码）。"""
    lines = ["上一轮没有通过验收，请继续在这个仓库里修（不要改 tests/）："]
    for failure in (result.get("accept") or {}).get("failures", [])[:8]:
        tail = [ln for ln in (failure.get("message") or "").splitlines() if ln.strip()]
        lines.append(f"- {failure.get('test')}: {tail[-1][:160] if tail else ''}")
    lines.append("改完自己跑一遍 python -m unittest discover -s tests -v，再说明改了什么。")
    return "\n".join(lines)


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
    ap.add_argument("--max-rounds", type=int, default=1,
                    help="不过就喂回失败信息继续修，最多几轮（含指定的轮次）")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    workdir = Path(a.workdir).resolve()
    spec = json.loads((EVAL / "tasks" / f"{a.task}.json").read_text(encoding="utf-8"))
    prompt_files = spec.get("prompts") or [spec["prompt"]]
    prompts = [
        (EVAL / rel).read_text(encoding="utf-8").replace("{workdir}", str(workdir))
        for rel in prompt_files
    ]

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
        for index, text in enumerate(prompts, 1):
            print(f"--- round {index} ---")
            print(text)
        return 0

    log(log_path, "start", task=a.task, rep=a.rep, workdir=str(workdir), rounds=len(prompts))
    click_label("新建任务")
    time.sleep(2)

    approvals = 0
    started = time.time()
    last_change = started
    ok = True

    def run_grade():
        grade_cmd = [
            sys.executable, str(HERE / "grade.py"),
            "--task", a.task, "--workdir", str(workdir), "--before", str(before),
            "--out", a.out, "--rep", str(a.rep), "--tool", a.tool,
            "--duration", str(round(last_change - started, 1)),
            "--interventions", str(approvals),
        ]
        graded = subprocess.run(grade_cmd, capture_output=True, text=True, encoding="utf-8")
        print((graded.stdout or "").strip())
        if graded.returncode != 0 and "result ->" not in (graded.stdout or ""):
            print((graded.stderr or "")[-800:], file=sys.stderr)
        out = Path(a.out)
        return json.loads(out.read_text(encoding="utf-8")) if out.exists() else None

    index = 0
    result = None
    while True:
        index += 1
        if index <= len(prompts):
            prompt = prompts[index - 1]
        else:
            # 指定的轮次都跑完了，还没过就喂回失败信息继续修，最多到 max_rounds
            if result is None or result.get("verdict") == "pass" or index > a.max_rounds:
                index -= 1
                break
            prompt = build_feedback(result)
            log(log_path, "feedback", round=index)
        if index > 1:
            log(log_path, "round", round=index)
            time.sleep(2)
        if not click_editor(log_path):
            raise SystemExit(f"editor not clickable at round {index}")
        clear_editor()
        state = editor_info()
        if not state or state["len"] > 1:  # 空编辑区是一个换行
            raise SystemExit(f"editor not empty before typing (round {index}): {state}")

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
            raise SystemExit(f"prompt not inserted (round {index}): {state}")
        log(log_path, "typed", round=index, chars=state["len"])

        cdp("key", "Enter", check=True)
        if index == 1:
            started = time.time()
        time.sleep(1.5)
        after = editor_info()
        if after and after["len"] >= 80 and after["text"] == state["text"]:
            # 回车没提交：试发送按钮
            for label in ("发送", "Send"):
                if click_label(label):
                    log(log_path, "send-button", label=label)
                    break
        log(log_path, "submit", round=index)

        round_ok, round_approvals, last_change = wait_done(
            log_path, a.timebox, a.debug, a.idle
        )
        approvals += round_approvals
        ok = ok and round_ok
        log(
            log_path,
            "round-done",
            round=index,
            finished=round_ok,
            approvals=round_approvals,
        )
        result = run_grade()

    took = round(time.time() - started, 1)
    measured = round(last_change - started, 1) if last_change else took
    try:
        cdp("shot", str(Path(a.out).with_suffix(".png")))
    except Exception:
        pass

    if result is not None:
        result["rounds"] = index
        result["rounds_to_pass"] = index if result.get("verdict") == "pass" else None
        Path(a.out).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    log(log_path, "graded", finished=ok, approvals=approvals,
        wall_s=took, measured_s=measured, rounds=index,
        verdict=(result or {}).get("verdict"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
