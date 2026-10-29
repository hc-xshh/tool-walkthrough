"""用 CDP 驱动 Cursor 3.x Agents 窗口跑一次 code-eval 任务，然后交给 grade.py 判分。

流程：
  1. prepare（可选）
  2. 用 `cursor.cmd <workdir>` 让已运行的 Cursor 打开该目录（复用同一个实例）
  3. 点 composer → 清空 → Input.insertText 写入任务书（UTF-8，不经 PowerShell）
  4. Enter 发送，轮询：自动点 Allow/Run；Stop 按钮消失且文本稳定即完成
  5. grade.py 判分

用法：
  python code-eval/tools/drive_cursor.py --task L1-split-bill \
      --workdir runs/x/work/L1-r1 --rep 1 --out runs/x/results/L1-r1.json \
      --prepare --force
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
REPO = EVAL.parent
CDP = [sys.executable, str(REPO / "harness" / "cdp.py"), "--port", "9562"]
EDITOR = '[contenteditable="true"]'
CURSOR_CLI = os.environ.get("CURSOR_CLI", r"D:\cursor\resources\app\bin\cursor.cmd")
APPROVE = ("Allow", "Allow once", "Allow for this session", "Run", "Accept", "Approve",
           "允许", "允许一次", "运行", "同意")
TMP_JS = HERE / "_cursor_tmp.js"


def cdp(op, arg=None, timeout=90, check=False):
    cmd = CDP + [op] + ([arg] if arg else [])
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f"cdp {op} failed: {(p.stdout + p.stderr)[-600:]}")
    return p


def js(source, timeout=60):
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


def buttons():
    return js("""(() => Array.from(document.querySelectorAll('button'))
      .filter(e => e.offsetParent !== null)
      .map(e => (e.innerText || e.getAttribute('aria-label') || '').trim())
      .filter(Boolean))()""") or []


def click_button(label):
    return js(f"""(() => {{
      const want = {json.dumps(label, ensure_ascii=False)};
      const el = Array.from(document.querySelectorAll('button'))
        .filter(e => e.offsetParent !== null &&
                (e.innerText || e.getAttribute('aria-label') || '').trim() === want)
        .pop();
      if (!el) return 'not found';
      el.scrollIntoView({{block:'center'}}); el.click(); return 'clicked';
    }})()""")


def editor_rect():
    return js(f"""(() => {{
      const el = document.querySelector('{EDITOR}');
      if (!el) return null;
      el.scrollIntoView({{block:'center'}});
      const r = el.getBoundingClientRect();
      return {{x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2),
               w: Math.round(r.width)}};
    }})()""")


def open_workspace(path, log_path):
    if path.name in page_text() and isinstance(editor_rect(), dict) and "Send message" in " ".join(buttons()):
        log(log_path, "workspace_already", name=path.name)
        return True
    p = subprocess.run([CURSOR_CLI, str(path)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    log(log_path, "open_workspace", rc=p.returncode, out=(p.stdout + p.stderr)[-200:])
    deadline = time.time() + 60
    while time.time() < deadline:
        if path.name in page_text() and isinstance(editor_rect(), dict) \
                and "Send message" in " ".join(buttons()):
            time.sleep(2)
            return True
        time.sleep(1)
    return False


def editor_len():
    n = js(f"""(() => {{
      const el = document.querySelector('{EDITOR}');
      return el ? (el.innerText || '').length : -1;
    }})()""")
    return n if isinstance(n, int) else -1


def send_prompt(prompt, log_path):
    for attempt in range(1, 4):
        # Wait until the composer is idle and present.
        deadline = time.time() + 20
        while time.time() < deadline:
            if isinstance(editor_rect(), dict) and not any("Stop" in x for x in buttons()):
                break
            time.sleep(1)
        r = editor_rect()
        if not isinstance(r, dict):
            log(log_path, "editor_missing", attempt=attempt)
            time.sleep(2)
            continue
        cdp("clickxy", f"{r['x']},{r['y']}")
        time.sleep(0.4)
        cdp("keycombo", "ctrl+a")
        cdp("key", "Backspace")
        time.sleep(0.3)
        cdp("type", prompt, timeout=60)
        time.sleep(0.8)
        got = editor_len()
        if got < len(prompt) * 0.6:
            log(log_path, "insert_short", attempt=attempt, got=got, want=len(prompt))
            time.sleep(0.5)
            continue
        cdp("key", "Enter")
        log(log_path, "sent", attempt=attempt, chars=got)
        time.sleep(3)
        # If the text is still in the composer and nothing is running, send again.
        if editor_len() > 20 and not any("Stop" in x for x in buttons()):
            cdp("key", "Enter")
            log(log_path, "resent")
        return True
    return False


def approve_once(log_path):
    for label in APPROVE:
        if click_button(label) == "clicked":
            log(log_path, "approve", label=label)
            time.sleep(1.5)
            return True
    return False


def wait_done(log_path, timebox, idle_s=30):
    deadline = time.time() + timebox
    last, last_change = "", time.time()
    stable = 0
    seen_stop = False
    while time.time() < deadline:
        text = page_text()
        labels = buttons()
        if text != last:
            last, last_change = text, time.time()
        if approve_once(log_path):
            continue
        stop = any("Stop" in x or "停止" in x for x in labels)
        if stop:
            seen_stop = True
        working = stop or "Stop generation" in text
        if seen_stop and not working:
            stable += 1
            if stable >= 4:
                log(log_path, "done", idle=round(time.time() - last_change, 1))
                return True
        else:
            stable = 0
        if seen_stop and not working and time.time() - last_change > idle_s:
            log(log_path, "done_idle")
            return True
        time.sleep(2)
    log(log_path, "timeout")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--out", required=True)
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--timebox", type=int, default=900)
    ap.add_argument("--tool", default="Cursor")
    ap.add_argument("--idle", type=int, default=30)
    ap.add_argument("--max-rounds", type=int, default=1)
    a = ap.parse_args()

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

    before = workdir.parent / (workdir.name + ".before.json")
    if not open_workspace(workdir, log_path):
        raise SystemExit("workspace open failed")

    started = time.time()
    ok = True
    for index, prompt in enumerate(prompts, 1):
        if not send_prompt(prompt, log_path):
            raise SystemExit(f"prompt insert failed (round {index})")
        ok = wait_done(log_path, a.timebox, a.idle)
        if not ok:
            log(log_path, "round_timeout", round=index)
            break
    elapsed = round(time.time() - started, 1)

    cmd = [sys.executable, str(HERE / "grade.py"),
           "--task", a.task, "--workdir", str(workdir), "--before", str(before),
           "--out", a.out, "--rep", str(a.rep), "--tool", a.tool,
           "--duration", str(elapsed)]
    g = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    print((g.stdout or "").strip()[-2000:])
    if g.returncode != 0:
        print((g.stderr or "")[-800:], file=sys.stderr)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
