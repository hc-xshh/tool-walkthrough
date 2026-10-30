"""用 CDP 驱动 Qoder CN 跑一次 code-eval 任务，然后交给 grade.py 判分。

与 drive_trae.py 的区别：
- Qoder 的每个任务在自己的工作区里跑（工作区 = 任务目录），避免跨任务串味；
- 工作区用「新建工作区」对话框 + 原生文件夹选择器创建，原生对话框由 harness/pick-folder.ps1 处理；
- 完成判据 = 见过「停止」按钮（这一轮在工作）后它变回「Send message」、且出现
  「由 AI 生成」，再稳定 3 次轮询。旧版的「正在执行中」文案仍然兼容。

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
import stall  # noqa: E402  (same directory; stall diagnostics)
from driver_core import CDP_SCRIPT, Cdp, log, wait_for  # noqa: E402

CDP = Cdp([sys.executable, str(CDP_SCRIPT), "--port", "9444"], "_qoder_tmp.js")
EDITOR = '[contenteditable="true"]'
APPROVE_LABELS = ("本次会话允许", "允许", "运行", "同意", "接受")
# "接受" is also the label on terms/licence dialogs, which are not ours to
# accept. Only treat it as an approval when the page asks to run a command.
APPROVE_CONTEXT = ("终端运行", "运行命令", "执行命令", "自动执行")
APPROVE_GATED = tuple(label for label in APPROVE_LABELS if label != "接受")
# "确定开启终端自动执行？": never confirmed — auto-run is a global setting and
# it would hide the approvals this harness counts.
AUTO_EXEC_MARKER = "确定开启终端自动执行"
# Qoder 1.37 renamed the entry point; keep both so older builds still work.
NEW_TASK_LABELS = ("新的任务", "新会话", "新建任务")
TRUST_LABELS = ("是，我信任此作者", "信任此作者")
PS1 = CDP_SCRIPT.parent / "pick-folder.ps1"


def approval_labels(text):
    """Which labels may be clicked on this page.

    "接受" is a plain confirmation on Qoder's terminal-run prompt ("终端运行 /
    拒绝 / 接受") but also on terms dialogs, so it is only offered when the page
    actually asks about running a command.
    """
    if any(marker in text for marker in APPROVE_CONTEXT):
        return APPROVE_LABELS
    return APPROVE_GATED


def page_text():
    p = CDP.run("text")
    if p.returncode != 0:
        # CDP is down or websocket-client is missing; say so once instead of
        # letting every wait_for() report "element not found".
        detail = ((p.stderr or "") + (p.stdout or "")).strip().splitlines()
        if detail:
            print(f"cdp text failed: {detail[-1][:300]}", file=sys.stderr)
        return ""
    return p.stdout


def click_aria(label):
    return CDP.js(f"""(() => {{
      const el = document.querySelector('[aria-label="{label}"]');
      if (!el) return 'not found';
      el.scrollIntoView({{block:'center'}});
      el.click();
      return 'clicked';
    }})()""")


def click_text_exact(label):
    """Click by label with the real pointer; JS .click() only as a fallback.

    Qoder's Monaco dialogs (folder trust, workspace prompts) ignore synthetic
    DOM clicks: the call reports success, the modal stays up, and the composer
    underneath stays covered. `cdp.py clickel` dispatches real mouse events.
    """
    if CDP.run("clickel", label, timeout=60).returncode == 0:
        return "clicked"
    return CDP.js(f"""(() => {{
      const els = Array.from(document.querySelectorAll('button,div,span,a,li'))
        .filter(e => e.offsetParent !== null && (e.innerText || '').trim() === {json.dumps(label)});
      const el = els[els.length - 1];
      if (!el) return 'not found';
      el.scrollIntoView({{block:'center'}});
      el.click();
      return 'clicked';
    }})()""")


def click_run_confirm():
    """Click Qoder's terminal-run button; return its label, or None.

    1.37 labels it "终端运行 Ctrl ↩" as a split button. Two things matter:

    * match by prefix — an exact label never fires once the shortcut is part
      of the text;
    * click the element itself, in the same JS call that finds it. Measuring
      the rect first and clicking it from a second process loses the race with
      the chat re-rendering: the footer buttons shift and the click lands on
      the neighbouring "开启终端自动执行" switch.
    """
    prefixes = json.dumps(list(dialogs.RUN_CONFIRM_PREFIXES), ensure_ascii=False)
    label = CDP.js(f"""(() => {{
      const prefixes = {prefixes};
      // A modal is on top: the card underneath is still in the DOM, and a
      // synthetic click would reach it through the backdrop.
      const modal = Array.from(document.querySelectorAll('[aria-modal="true"], .monaco-dialog-box'))
        .some(e => e.offsetParent !== null);
      if (modal) return null;
      for (const el of document.querySelectorAll('button,[role="button"]')) {{
        if (!el.offsetParent || el.disabled) continue;
        const text = (el.innerText || '').trim();
        if (!prefixes.some(p => text.startsWith(p))) continue;
        el.click();
        return text;
      }}
      return null;
    }})()""")
    return label if isinstance(label, str) and label else None


def dismiss_auto_exec(log_path, where):
    """Cancel Qoder's "开启终端自动执行？" confirmation.

    Enabling auto-run is a global policy change (and would hide the approvals
    this harness measures), so the answer is always "取消". Only the dialog's
    own button is clicked: the chat card underneath has a "取消" too.
    """
    marker = AUTO_EXEC_MARKER
    if marker not in page_text():
        return False
    rect = CDP.js("""(() => {
      const dlg = document.querySelector('[aria-modal="true"], .monaco-dialog-box');
      if (!dlg) return null;
      const b = Array.from(dlg.querySelectorAll('button'))
        .find(e => (e.innerText || '').trim() === '取消');
      if (!b) return null;
      const r = b.getBoundingClientRect();
      return {x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2)};
    })()""")
    if not isinstance(rect, dict):
        log(log_path, "auto_exec_cancel_missing", where=where)
        return False
    CDP.run("clickxy", f"{rect['x']},{rect['y']}")
    ok = wait_for(lambda: marker not in page_text(), 8, label="auto-exec-dialog")
    log(log_path, "auto_exec_cancelled", where=where, ok=ok)
    return ok


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
    chip = CDP.js("""(() => {
      const els = Array.from(document.querySelectorAll('div[class*="new-chat-workspace"] button'));
      const el = els[els.length - 1];
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return {x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
              label: (el.innerText || '').trim()};
    })()""")
    if isinstance(chip, dict):
        CDP.run("clickxy", f"{chip['x']},{chip['y']}")
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
    out = CDP.js("""(() => {
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
        CDP.run("shot", str(path), timeout=30)
        return str(path)
    except Exception:  # noqa: BLE001 - evidence is best effort
        return None


def guard_dialogs(log_path, where):
    """Safe dialogs are handled; blocked/unknown ones stop the run with evidence."""
    if dismiss_auto_exec(log_path, where):
        return "handled"
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


def dismiss_trust(log_path, attempts=3):
    """Answer Qoder's folder-trust prompt, and verify it really closed.

    A click that "succeeds" while the modal stays up is worse than no click:
    the run then types into the backdrop. Every attempt re-reads the page and
    retries with a real pointer click.
    """
    for attempt in range(1, attempts + 1):
        if "信任此作者" not in page_text():
            return True
        clicked = None
        for label in TRUST_LABELS:
            if click_text_exact(label) == "clicked":
                clicked = label
                break
        if not clicked:
            log(log_path, "trust_missing", attempt=attempt)
            return False
        log(log_path, "trust_accepted", label=clicked, attempt=attempt)
        if wait_for(lambda: "信任此作者" not in page_text(), 10, label="trust-dialog"):
            return True
    log(log_path, "trust_stuck")
    return False


def editor_info():
    return CDP.js(f"""(() => {{
      const el = document.querySelector('{EDITOR}');
      if (!el) return null;
      return {{len: (el.innerText || '').length}};
    }})()""")


def editor_rect():
    """Composer centre, or '__covered__' when a modal sits on top of it."""
    return CDP.js(f"""(() => {{
      const el = document.querySelector('{EDITOR}');
      if (!el) return null;
      const r = el.getBoundingClientRect();
      if (r.width < 40 || r.height < 10) return null;
      const hit = document.elementFromPoint(r.x + r.width/2, r.y + r.height/2);
      if (!(hit === el || el.contains(hit))) return '__covered__';
      return {{x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2)}};
    }})()""")


def new_task(log_path):
    for label in NEW_TASK_LABELS:
        if click_text_exact(label) == "clicked":
            log(log_path, "new_task", label=label)
            break
    ok = wait_for(lambda: isinstance(editor_info(), dict), 20, label="editor")
    log(log_path, "new_task", ok=ok)
    return ok


def fill_editor(prompt, log_path):
    """Click the composer, clear it, type `prompt`; returns the inserted length."""
    rect = editor_rect()
    if rect == "__covered__":
        # A modal (folder trust, quota, update) is over the composer. Clear it
        # instead of typing into the backdrop.
        guard_dialogs(log_path, "composer-covered")
        rect = editor_rect()
    if rect == "__covered__":
        log(log_path, "composer_covered")
        return 0
    if not isinstance(rect, dict):
        log(log_path, "composer_missing")
        return 0
    CDP.run("clickxy", f"{rect['x']},{rect['y']}")
    time.sleep(0.3)
    CDP.run("keycombo", "ctrl+a")
    CDP.run("key", "Backspace")
    time.sleep(0.2)
    CDP.run("type", prompt, timeout=60)
    time.sleep(0.5)
    inserted = editor_info()
    return inserted.get("len", 0) if isinstance(inserted, dict) else 0


def send_prompt(prompt, log_path):
    guard_dialogs(log_path, "before-send")
    if not isinstance(editor_info(), dict):
        return False
    got = fill_editor(prompt, log_path)
    if got < len(prompt) * 0.6:
        # The first insert can land nowhere while the window is still
        # restoring; one retry covers that without masking a changed selector.
        log(log_path, "insert_retry", got=got, want=len(prompt))
        time.sleep(1.5)
        got = fill_editor(prompt, log_path)
    if got < len(prompt) * 0.6:
        log(log_path, "insert_failed", got=got, want=len(prompt))
        return False
    # A slash/at mention popup can swallow Enter; close it before sending.
    if "指令或扩展能力" in page_text():
        CDP.run("key", "Escape")
        time.sleep(0.4)
    CDP.run("key", "Enter")
    log(log_path, "sent", chars=got)
    # Retry once if the composer still holds the text and nothing is running.
    time.sleep(4)
    current = page_text()
    still = editor_info()
    if isinstance(still, dict) and still.get("len", 0) > 20 and "正在执行中" not in current:
        CDP.run("key", "Enter")
        log(log_path, "resent")
        time.sleep(2)
        again = editor_info()
        if isinstance(again, dict) and again.get("len", 0) > 20:
            # Some builds need the button; Enter only inserts a newline.
            clicked = CDP.js("""(() => {
              const b = document.querySelector('[aria-label="Send message"], [aria-label="发送"]');
              if (!b) return 'not found';
              b.click();
              return 'clicked';
            })()""")
            log(log_path, "send_button", result=clicked)
    return True


def approve_native(label):
    """Click the approval button with the real pointer; its split menu needs a second click."""
    rect = CDP.js(f"""(() => {{
      const els = Array.from(document.querySelectorAll('button,[role="button"]'))
        .filter(e => e.offsetParent !== null && (e.innerText || '').trim() === {json.dumps(label)});
      const el = els[els.length - 1];
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return {{x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2)}};
    }})()""")
    if not isinstance(rect, dict):
        return False
    CDP.run("clickxy", f"{rect['x']},{rect['y']}")
    time.sleep(0.6)
    for item in ("允许一次", "本次任务允许"):
        item_rect = CDP.js(f"""(() => {{
          const els = Array.from(document.querySelectorAll('button,div,span'))
            .filter(e => e.offsetParent !== null && (e.innerText || '').trim() === {json.dumps(item)});
          const el = els[els.length - 1];
          if (!el) return null;
          const r = el.getBoundingClientRect();
          return {{x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2)}};
        }})()""")
        if isinstance(item_rect, dict):
            CDP.run("clickxy", f"{item_rect['x']},{item_rect['y']}")
            return True
    return True


def turn_active():
    """True while Qoder is working on a turn.

    1.37 never prints "正在执行中": the composer's send button becomes "停止"
    for the whole turn, including while a run prompt waits for a click. Without
    this the finished run never looked finished and every attempt waited out
    the whole timebox.
    """
    return bool(CDP.js("""(() => {
      const stop = document.querySelector('[aria-label="停止"], [aria-label="Stop"]');
      return !!(stop && stop.offsetParent !== null);
    })()"""))


def wait_done(log_path, timebox, idle_s=30, debug=False, stall_timeout=180):
    deadline = time.time() + timebox
    started = time.time()
    last_report = started
    next_stall = 0.0
    stall_reports = 0
    warned_unmatched = False
    seen_active = False
    stable = 0
    last = ""
    last_change = time.time()
    approvals = 0
    run_clicks = 0
    while time.time() < deadline:
        now = time.time()
        current = page_text()
        if current != last:
            last, last_change = current, now
            run_clicks = 0
        streaming = "正在执行中" in current  # older Qoder builds
        running = streaming or turn_active()
        if running:
            seen_active = True
        label = CDP.pending_label(approval_labels(current))
        run_label = None if label else click_run_confirm()
        if label:
            approve_native(label)
            approvals += 1
            log(log_path, "approve", label=label)
            time.sleep(2)
            continue
        if run_label and run_clicks < 3:
            # Cap the retries: a click that does not close the card must not
            # keep the loop from noticing the run is already finished.
            run_clicks += 1
            approvals += 1
            log(log_path, "approve", label=run_label, reason="终端运行")
            time.sleep(2)
            continue
        if "拒绝" in current and "接受" in current and not warned_unmatched:
            # A confirmation the driver does not recognise: say so once instead
            # of sitting here silently until the timebox runs out.
            warned_unmatched = True
            print("[qoder] 界面上有未识别的确认框（拒绝/接受），可能在等人点", flush=True)
            log(log_path, "approval_unrecognised")

        if stall_timeout and not streaming and now - last_change >= stall_timeout and now >= next_stall:
            # Nothing moved for a while. Look at the screen instead of waiting
            # for the timebox: a known prompt is clicked, a blocked one stops
            # the run with evidence, an unrecognised frozen screen stops too.
            tag = f"{Path(log_path).stem}-stall{stall_reports + 1}"
            report = stall.diagnose(CDP, Path(log_path).parent, tag, current)
            stall_reports += 1
            next_stall = now + stall_timeout
            log(log_path, "stall", verdict=report["verdict"], frozen=report["frozen"],
                ocr=report["ocr"], evidence=report["evidence"])
            print(f"[qoder] 界面 {int(now - last_change)}s 无进展 → {report['verdict']}"
                  f"（{report.get('reason') or '-'}；证据 {report['evidence']}）", flush=True)
            if report["verdict"] == "handled":
                click = report.get("click")
                if click:
                    CDP.run("clickxy", f"{click['x']},{click['y']}")
                else:
                    approve_native(report["label"])
                approvals += 1
                log(log_path, "stall_handled", label=report["label"],
                    reason=report.get("reason"), via=report.get("via"))
                last_change = time.time()
                continue
            if report["verdict"] in ("blocked", "dead"):
                log(log_path, "stall_stopped", verdict=report["verdict"],
                    reason=report.get("reason"), evidence=report["evidence"])
                raise SystemExit(
                    f"界面停在「{report.get('reason') or report['verdict']}」"
                    f"（{report['verdict']}），已留证：{report['evidence']}")
            if report["frozen"] and stall_reports >= 2:
                raise SystemExit(f"界面冻结、没有可点的已知按钮，已留证：{report['evidence']}")
        if seen_active and not running and "由 AI 生成" in current:
            stable += 1
            if stable >= 3:
                log(log_path, "done", approvals=approvals, idle=round(time.time() - last_change, 1))
                return True, approvals
        else:
            stable = 0
        if seen_active and not running and time.time() - last_change > idle_s:
            log(log_path, "done_idle", approvals=approvals)
            return True, approvals
        if not streaming:
            # A dialog that appears mid-run is handled here; blocked/unknown
            # ones raise and end the attempt with a screenshot.
            guard_dialogs(log_path, "idle")
        if time.time() - last_report > 60:
            last_report = time.time()
            print(f"[qoder] 等待中 {int(time.time() - started)}s"
                  f"（界面 {int(time.time() - last_change)}s 无变化，approvals={approvals}）",
                  flush=True)
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
    ap.add_argument("--stall-timeout", type=int, default=180,
                    help="界面多久没变化就截图/OCR 诊断（秒；0 关闭）")
    ap.add_argument("--skip-workspace", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="只报告 CDP/界面结构，不点击、不发送")
    a = ap.parse_args()

    global CDP
    CDP = Cdp(
        [sys.executable, str(CDP_SCRIPT), "--port", "9444",
         "--match-title", Path(a.workdir).name],
        "_qoder_tmp.js",
    )

    probe = CDP.run("text", timeout=15)
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
        ok, approvals = wait_done(log_path, a.timebox, a.idle, a.debug, a.stall_timeout)
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
