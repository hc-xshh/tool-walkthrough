"""从 trace 里量真实耗时：提交 → 界面最后一次变化。

drive_trae 的 45 秒空闲兜底会拖长 wall time；界面文本停止变化的那一刻更接近
「任务真的干完了」，所以记分卡用这个数，不用 wall time。

用法：python tools/timing.py --run runs/<run>
"""

import argparse
import json
from datetime import datetime
from pathlib import Path


def seconds_between(a, b):
    fmt = "%H:%M:%S"
    return (datetime.strptime(b, fmt) - datetime.strptime(a, fmt)).total_seconds()


def measure(trace_path):
    submit = None
    last_state = None
    approvals = 0
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event["event"] == "submit":
            submit = event["ts"]
        elif event["event"] == "state":
            last_state = event["ts"]
        elif event["event"] == "approve":
            approvals += 1
    if not submit or not last_state:
        return None
    return {"duration_s": seconds_between(submit, last_state), "approvals": approvals}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    rows = {}
    for trace in sorted(Path(a.run, "results").glob("*.trace.jsonl")):
        got = measure(trace)
        if got:
            rows[trace.name.replace(".trace.jsonl", "")] = got
            print(f"{trace.stem:<26} {got['duration_s']:>6.0f}s  approvals={got['approvals']}")
    out = Path(a.run, "results", "timing.json")
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
