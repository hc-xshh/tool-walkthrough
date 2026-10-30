"""用 CDP 驱动 Qoder CN 跑一次 code-eval 任务，然后交给 grade.py 判分。

与 drive_trae.py 的区别：
- Qoder 的每个任务在自己的工作区里跑（工作区 = 任务目录），避免跨任务串味；
- 工作区用「新建工作区」对话框 + 原生文件夹选择器创建，原生对话框由 qoder_folder.ps1 处理；
- 完成判据 = 见过「正在执行中」后它消失、且出现「由 AI 生成」，再稳定 3 次轮询。

用法：
  python code-eval/tools/drive_qoder.py --task L1-split-bill \
      --workdir runs/x/work/L1-split-bill-r1 --rep 1 \
      --out runs/x/results/L1-split-bill-r1.json --prepare --force
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
sys.path.insert(0, str(HERE))
import dialogs  # noqa: E402  (same directory; rules live there)
REPO = EVAL.parent
CDP = [sys.executable, str(REPO / "harness" / "cdp.py"), "--port", "9444"]
MATCH_TITLE = None  # set from the task folder so several windows are not ambiguous
EDITOR = '[contenteditable="true"]'
APPROVE_LABELS = ("本次会话允许", "允许", "运行", "同意")
# Qoder 1.37 renamed the entry point; keep both so older builds still work.
NEW_TASK_LABELS = ("新的任务", "新会话", "新建任务")
TRUST_LABELS = ("是，我信任此作者", "信任此作者")
PS1 = REPO / "harness" / "pick-folder.ps1"


def cdp(op, arg=None, timeout=90, check=False):
    cmd = CDP + ([ "--match-title", MATCH_TITLE ] if MATCH_TITLE else []) + [op] + ([arg] if arg else [])
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f"cdp {op} failed: {(p.stdout + p.stderr)[-600:]}")
    return p


def js(source, timeout=60):
    tmp = HERE / "_qoder_tmp.js"
    tmp.write_text(source, encoding="utf-8")
    try:
        p = cdp("eval", "@" + str(tmp), timeout=timeout)
    finally:
        tmp.unlink(missing_ok=True)
    if p.returncode != 0:
        return None
    raw = p.stdout.strip()
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def page_text():
    p = cdp("text")
    if p.returncode != 0:
        # CDP is down or websocket-client is missing; say so once instead of
        # letting every wait_for() report "element not found".
        detail = ((p.stderr or "") + (p.stdout or "")).strip().splitlines()
        if detail:
            print(f"cdp text failed: {detail[-1][:300]}", file=sys.stderr)
        return ""
    return p.stdout


def log(path, event, **fields):
    rec = {"ts": time.strftime("%H:%M:%S"), "event": event, **fields}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def click_aria(label):
    return js(f"""(() => {{
      const el = document.querySelector('[aria-label="{label}"]');
      if (!el) return 'not found';
      el.scrollIntoView({{block:'center'}});
      el.click();
      return 'clicked';
    }})()""")


def click_text_exact(label):
    return js(f"""(() => {{
      const els = Array.from(document.querySelectorAll('button,div,span,a,li'))
        .filter(e => e.offsetParent !== null && (e.innerText || '').trim() === {json.dumps(label)});
      const el = els[els.length - 1];
      if (!el) return 'not found';
      el.scrollIntoView({{block:'center'}});
      el.click();
      return 'clicked';
    }})()""")


def wait_for(predicate, timeout, interval=1.0, label=""):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    print(f"timeout waiting for {label}", file=sys.stderr)
    return False


def pick_folder(path):
    if os.name != "nt":
        return False, ("native folder picker is Windows-only (harness/pick-folder.ps1); "
                       "create the workspace in Qoder by hand, then rerun with "
                       "--skip-workspace")
    p = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PS1), str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    return p.returncode == 0, (p.stdout + p.stderr).strip()


def ensure_workspace(path, log_path, timeout=120):
    """Create and activate a Qoder workspace rooted at `path`."""
    text_before = page_text()
    if path.name in text_before and ("暂无任务" in text_before or "新会话" in text_before):
        log(log_path, "workspace_exists", name=path.name)
        return True
    # The workspace chip is only clickable on the home screen, not inside a task.
    click_text_exact("新的任务")
    time.sleep(1.5)
    chip = js("""(() => {
      const els = Array.from(document.querySelectorAll('div[class*="new-chat-workspace"] button'));
      const el = els[els.length - 1];
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return {x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
              label: (el.innerText || '').trim()};
    })()""")
    if isinstance(chip, dict):
        cdp("clickxy", f"{chip['x']},{chip['y']}")
        log(log_path, "chip_click", label=chip.get("label"), xy=f"{chip['x']},{chip['y']}")
    if not wait_for(lambda: "新建工作区" in page_text(), 10, label="workspace-popover"):
        log(log_path, "popover_missing", text=page_text()[:300])
        return False
    click_text_exact("新建工作区")
    if not wait_for(lambda: "源文件夹" in page_text(), 15, label="new-workspace-dialog"):
        return False
    log(log_path, "dialog_open")
    click_text_exact("点击添加可读写文件夹")
    time.sleep(1.5)
    ok, detail = pick_folder(path)
    log(log_path, "folder_pick", ok=ok, detail=detail[:200])
    if not ok:
        return False
    time.sleep(1.0)
    click_text_exact("创建")
    ok = wait_for(lambda: "源文件夹" not in page_text(), 30, label="dialog_close")
    time.sleep(1.5)
    log(log_path, "workspace_created", name=path.name, ok=ok)
    return ok


def page_dialogs():
    """Visible modal texts, used only when no rule matched."""
    out = js("""(() => {
      const sel = '[aria-modal="true"], .monaco-dialog-box';
      return Array.from(document.querySelectorAll(sel))
        .filter(e => e.offsetParent !== null)
        .map(e => ((e.innerText || '').trim().slice(0, 160)))
        .filter(t => t.length > 20);
    })()""")
    return out if isinstance(out, list) else []


def dialog_shot(log_path):
    path = Path(log_path).with_suffix(".dialog.png")
    try:
        cdp("shot", str(path), timeout=30)
        return str(path)
    except Exception:  # noqa: BLE001 - evidence is best effort
        return None


def guard_dialogs(log_path, where):
    """Safe dialogs are handled; blocked/unknown ones stop the run with evidence."""
    status, detail = dialogs.handle(
        page_text, click_text_exact,
        lambda event, **fields: log(log_path, event, **fields),
        where=where, shot=lambda: dialog_shot(log_path), dom=page_dialogs,
    )
    if status == "blocked":
        reason = detail.get("reason") or detail.get("marker")
        extra = f"；截图 {detail['screenshot']}" if detail.get("screenshot") else ""
        raise SystemExit(f"被弹窗挡住（{where}）：{reason}{extra}")
    if status == "unknown":
        raise SystemExit(f"遇到未知弹窗（{where}）：{detail.get('text', '')[:120]!r}"
                         f"{'；截图 ' + detail['screenshot'] if detail.get('screenshot') else ''}")
    return status


def dismiss_trust(log_path):
    """Qoder asks whether to trust the folder; the driver must answer it."""
    if "信任此作者" not in page_text():
        return True
    for label in TRUST_LABELS:
        if click_text_exact(label) == "clicked":
            log(log_path, "trust_accepted", label=label)
            return wait_for(lambda: "信任此作者" not in page_text(), 10, label="trust-dialog")
    log(log_path, "trust_missing")
    return False


def editor_info():
    return js(f"""(() => {{
      const el = document.querySelector('{EDITOR}');
      if (!el) return null;
      return {{len: (el.innerText || '').length}};
    }})()""")


def new_task(log_path):
    for label in NEW_TASK_LABELS:
        if click_text_exact(label) == "clicked":
            log(log_path, "new_task", label=label)
            break
    ok = wait_for(lambda: isinstance(editor_info(), dict), 20, label="editor")
    log(log_path, "new_task", ok=ok)
    return ok


def send_prompt(prompt, log_path):
    guard_dialogs(log_path, "before-send")
    info = editor_info()
    if not isinstance(info, dict):
        return False
    rect = js(f"""(() => {{
      const el = document.querySelector('{EDITOR}');
      const r = el.getBoundingClientRect();
      return {{x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2)}};
    }})()""")
    if isinstance(rect, dict):
        cdp("clickxy", f"{rect['x']},{rect['y']}")
        time.sleep(0.3)
    cdp("keycombo", "ctrl+a")
    cdp("key", "Backspace")
    time.sleep(0.2)
    cdp("type", prompt, timeout=60)
    time.sleep(0.5)
    inserted = editor_info()
    got = inserted.get("len", 0) if isinstance(inserted, dict) else 0
    if got < len(prompt) * 0.6:
        log(log_path, "insert_failed", got=got, want=len(prompt))
        return False
    # A slash/at mention popup can swallow Enter; close it before sending.
    if "指令或扩展能力" in page_text():
        cdp("key", "Escape")
        time.sleep(0.4)
    cdp("key", "Enter")
    log(log_path, "sent", chars=got)
    # Retry once if the composer still holds the text and nothing is running.
    time.sleep(4)
    current = page_text()
    still = editor_info()
    if isinstance(still, dict) and still.get("len", 0) > 20 and "正在执行中" not in current:
        cdp("key", "Enter")
        log(log_path, "resent")
        time.sleep(2)
        again = editor_info()
        if isinstance(again, dict) and again.get("len", 0) > 20:
            # Some builds need the button; Enter only inserts a newline.
            clicked = js("""(() => {
              const b = document.querySelector('[aria-label="Send message"], [aria-label="发送"]');
              if (!b) return 'not found';
              b.click();
              return 'clicked';
            })()""")
            log(log_path, "send_button", result=clicked)
    return True


def pending_approval():
    labels = json.dumps(list(APPROVE_LABELS), ensure_ascii=False)
    return js(f"""(() => {{
      const labels = {labels};
      const els = Array.from(document.querySelectorAll('button,[role="button"],div,span'))
        .filter(e => e.offsetParent !== null);
      for (const label of labels) {{
        if (els.some(e => (e.innerText || '').trim() === label)) return label;
      }}
      return null;
    }})()""")


def approve_native(label):
    """Click the approval button with the real pointer; its split menu needs a second click."""
    rect = js(f"""(() => {{
      const els = Array.from(document.querySelectorAll('button,[role="button"]'))
        .filter(e => e.offsetParent !== null && (e.innerText || '').trim() === {json.dumps(label)});
      const el = els[els.length - 1];
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return {{x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2)}};
    }})()""")
    if not isinstance(rect, dict):
        return False
    cdp("clickxy", f"{rect['x']},{rect['y']}")
    time.sleep(0.6)
    for item in ("允许一次", "本次任务允许"):
        item_rect = js(f"""(() => {{
          const els = Array.from(document.querySelectorAll('button,div,span'))
            .filter(e => e.offsetParent !== null && (e.innerText || '').trim() === {json.dumps(item)});
          const el = els[els.length - 1];
          if (!el) return null;
          const r = el.getBoundingClientRect();
          return {{x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2)}};
        }})()""")
        if isinstance(item_rect, dict):
            cdp("clickxy", f"{item_rect['x']},{item_rect['y']}")
            return True
    return True


def wait_done(log_path, timebox, idle_s=30, debug=False):
    deadline = time.time() + timebox
    seen_running = False
    stable = 0
    last = ""
    last_change = time.time()
    approvals = 0
    while time.time() < deadline:
        current = page_text()
        if current != last:
            last, last_change = current, time.time()
        running = "正在执行中" in current
        if running:
            seen_running = True
        label = pending_approval()
        if label:
            approve_native(label)
            approvals += 1
            log(log_path, "approve", label=label)
            time.sleep(2)
            continue
        if seen_running and not running and "由 AI 生成" in current:
            stable += 1
            if stable >= 3:
                log(log_path, "done", approvals=approvals, idle=round(time.time() - last_change, 1))
                return True, approvals
        else:
            stable = 0
        if seen_running and time.time() - last_change > idle_s and not running:
            log(log_path, "done_idle", approvals=approvals)
            return True, approvals
        if not running and "正在执行中" not in current:
            # A dialog that appears mid-run is handled here; blocked/unknown
            # ones raise and end the attempt with a screenshot.
            guard_dialogs(log_path, "idle")
        if debug:
            print("STATE:", current.strip()[-160:].replace("\n", " | "))
        time.sleep(2)
    log(log_path, "timeout", approvals=approvals)
    return False, approvals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--out", required=True)
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--timebox", type=int, default=900)
    ap.add_argument("--tool", default="Qoder CN")
    ap.add_argument("--idle", type=int, default=30)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--skip-workspace", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="只报告 CDP/界面结构，不点击、不发送")
    a = ap.parse_args()

    global MATCH_TITLE
    MATCH_TITLE = Path(a.workdir).name

    probe = cdp("text", timeout=15)
    if probe.returncode != 0:
        detail = ((probe.stderr or "") + (probe.stdout or "")).strip()[-400:]
        raise SystemExit(
            "cannot reach Qoder CN over CDP on port 9444.\n"
            "Start Qoder CN with --remote-debugging-port=9444 first, e.g.\n"
            "  /usr/share/qoder-cn-ide/qoder-cn-ide --remote-debugging-port=9444\n"
            f"detail: {detail}"
        )

    if a.check:
        text = page_text()
        report = {
            "cdp": True,
            "chars": len(text),
            "new_task_labels": {label: label in text for label in NEW_TASK_LABELS},
            "trust_dialog": "信任此作者" in text,
            "editor": isinstance(editor_info(), dict),
            "workspace_chip": Path(a.workdir).name in text,
            "dialogs": dialogs.classify(text),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    workdir = Path(a.workdir).resolve()
    spec = json.loads((EVAL / "tasks" / f"{a.task}.json").read_text(encoding="utf-8"))
    prompt_files = spec.get("prompts") or [spec["prompt"]]
    prompts = [(EVAL / rel).read_text(encoding="utf-8").replace("{workdir}", str(workdir))
               for rel in prompt_files]

    log_path = Path(a.out).parent / (Path(a.out).stem + ".trace.jsonl")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")

    if a.prepare:
        cmd = [sys.executable, str(HERE / "prepare.py"), "--task", a.task, "--workdir", str(workdir)]
        if a.force:
            cmd.append("--force")
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if p.returncode != 0:
            raise SystemExit(f"prepare failed: {p.stderr}")
        print(p.stdout.strip())

    if not dismiss_trust(log_path):
        raise SystemExit("cannot dismiss the folder-trust dialog")
    guard_dialogs(log_path, "start")

    before = workdir.parent / (workdir.name + ".before.json")
    if not a.skip_workspace:
        if not ensure_workspace(workdir, log_path):
            raise SystemExit("workspace creation failed")

    started = time.time()
    if not new_task(log_path):
        raise SystemExit("cannot start a new task")

    ok = True
    approvals = 0
    for index, prompt in enumerate(prompts, 1):
        if not send_prompt(prompt, log_path):
            raise SystemExit(f"prompt insert failed (round {index})")
        ok, approvals = wait_done(log_path, a.timebox, a.idle, a.debug)
        if not ok:
            log(log_path, "round_timeout", round=index)
            break
    elapsed = round(time.time() - started, 1)

    grade_cmd = [
        sys.executable, str(HERE / "grade.py"),
        "--task", a.task, "--workdir", str(workdir), "--before", str(before),
        "--out", a.out, "--rep", str(a.rep), "--tool", a.tool,
        "--duration", str(elapsed), "--interventions", str(approvals),
    ]
    g = subprocess.run(grade_cmd, capture_output=True, text=True, encoding="utf-8")
    print((g.stdout or "").strip()[-2000:])
    if g.returncode != 0:
        print((g.stderr or "")[-800:], file=sys.stderr)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
