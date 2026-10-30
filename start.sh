#!/usr/bin/env bash
# Start the walkthrough workbench — exactly one instance, restarted by default.
#
#   ./start.sh                # stop any workbench we can find, start fresh on 8790
#   ./start.sh --port 8791    # ... on another port
#   ./start.sh --reuse        # keep a running instance instead of restarting
#   ./start.sh --force        # restart even if a run is still in flight
#
# No need to remember the terminal that started the old instance: the script
# probes the port (server.py identifies itself with a Server header) and reads
# the last start recorded in runs/workbench/server.json, then stops what it
# finds. A restart is refused while jobs are running unless --force is given.
#
# Windows: python workbench\server.py
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
SERVER="$ROOT/workbench/server.py"
STATE="$ROOT/runs/workbench/server.json"
DEFAULT_PORT=8790

usage() {
  cat <<'EOF'
用法: ./start.sh [--port N] [--host H] [--reuse] [--force] [-- <server.py 参数>]

  --port N   工作台端口（默认 8790）
  --reuse    不重启：已经在跑就直接复用（旧的幂等行为）
  --force    有任务在跑也强制重启
EOF
}

if ! command -v "$PY" >/dev/null 2>&1; then
  echo "start: 找不到 $PY；装 Python 3.9+，或用 PYTHON=/path/to/python3 ./start.sh" >&2
  exit 1
fi
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "start: 需要 Python 3.9+，当前是 $("$PY" -V 2>&1)" >&2
  exit 1
fi
if [ ! -f "$SERVER" ]; then
  echo "start: 缺少 $SERVER，工作台文件不完整" >&2
  exit 1
fi

# Read our own flags without consuming the rest: anything unknown still goes
# to server.py, so its argparse stays the source of truth for those.
port=$DEFAULT_PORT
host=127.0.0.1
port_given=0
host_given=0
reuse=0
force=0
extra=()
args=("$@")
i=0
while [ "$i" -lt "${#args[@]}" ]; do
  arg="${args[$i]}"
  case "$arg" in
    -h|--help)
      usage
      echo
      exec "$PY" -u "$SERVER" --help
      ;;
    --port)
      port="${args[$((i + 1))]:-}"
      port_given=1
      i=$((i + 2))
      ;;
    --port=*)
      port="${arg#*=}"
      port_given=1
      i=$((i + 1))
      ;;
    --host)
      host="${args[$((i + 1))]:-127.0.0.1}"
      host_given=1
      i=$((i + 2))
      ;;
    --host=*)
      host="${arg#*=}"
      host_given=1
      i=$((i + 1))
      ;;
    --reuse|--no-restart)
      reuse=1
      i=$((i + 1))
      ;;
    --force)
      force=1
      i=$((i + 1))
      ;;
    *)
      extra+=("$arg")
      i=$((i + 1))
      ;;
  esac
done

case "$port" in
  ''|*[!0-9]*)
    echo "start: --port 需要整数，收到 '$port'" >&2
    exit 1
    ;;
esac

# 0 = a workbench answers, 1 = some other service, 2 = nothing listening.
# The Server header comes from server.py, so a stray dev server never counts.
probe() {
  "$PY" - "$1" "$2" <<'PY'
import http.client, socket, sys

host, port = sys.argv[1], int(sys.argv[2])
try:
    conn = http.client.HTTPConnection(host, port, timeout=1.0)
    conn.request("GET", "/")
    server = conn.getresponse().getheader("Server") or ""
except (ConnectionError, OSError, socket.timeout):
    sys.exit(2)
sys.exit(0 if "WalkthroughWorkbench" in server else 1)
PY
}

# Bind test: the server has no busy-port fallback of its own.
port_free() {
  "$PY" - "$1" "$2" <<'PY'
import socket, sys

host, port = sys.argv[1], int(sys.argv[2])
sock = socket.socket()
# Same option HTTPServer uses: a TIME_WAIT left behind by the probe must not
# read as "port still taken", or a clean restart looks like a failed shutdown.
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    sock.bind((host, port))
except OSError:
    sys.exit(1)
finally:
    sock.close()
PY
}

# PID(s) listening on a TCP port, best effort across ss / lsof / fuser.
listener_pids() {
  local out=""
  if command -v ss >/dev/null 2>&1; then
    out=$(ss -ltnp 2>/dev/null | awk -v p=":$1" '$4 ~ p "$" {print}' \
      | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | sort -u | tr '\n' ' ')
  fi
  if [ -z "${out// /}" ] && command -v lsof >/dev/null 2>&1; then
    out=$(lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | sort -u | tr '\n' ' ')
  fi
  if [ -z "${out// /}" ] && command -v fuser >/dev/null 2>&1; then
    out=$(fuser -n tcp "$1" 2>/dev/null | tr -s ' ' | sed 's/^ //; s/ $//')
  fi
  printf '%s' "${out% }"
}

# Running jobs according to the instance itself; 0 when it cannot be asked.
running_jobs() {
  "$PY" - "$1" "$2" <<'PY'
import json, sys, urllib.request

host, port = sys.argv[1], int(sys.argv[2])
try:
    with urllib.request.urlopen(f"http://{host}:{port}/api/jobs", timeout=2) as resp:
        jobs = json.load(resp).get("jobs") or []
except Exception:
    print(0)
    raise SystemExit(0)
print(sum(1 for job in jobs if job.get("status") == "running"))
PY
}

announce_running() {
  echo "start: 工作台已在运行 → http://$1:$2/"
  echo "start: 没有重复启动；要重启去掉 --reuse，或直接再跑一次 ./start.sh"
  exit 0
}

# Last instance we started: {"host", "port"} in runs/workbench/server.json.
read_state() {
  [ -f "$STATE" ] || return 1
  local out
  out=$("$PY" - "$STATE" <<'PY'
import json, sys

try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        data = json.load(fh)
except (OSError, ValueError):
    sys.exit(1)
port = data.get("port")
if not isinstance(port, int):
    sys.exit(1)
print(f"{data.get('host') or '127.0.0.1'} {port}")
PY
  ) || return 1
  state_host="${out%% *}"
  state_port="${out##* }"
}

write_state() {
  mkdir -p "$(dirname "$STATE")"
  "$PY" - "$STATE" "$1" "$2" <<'PY'
import json, os, sys, tempfile
from datetime import datetime

path, host, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
data = {"host": host, "port": port, "url": f"http://{host}:{port}/",
        "started": datetime.now().isoformat(timespec="seconds")}
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".server.", suffix=".json")
with os.fdopen(fd, "w", encoding="utf-8") as fh:
    json.dump(data, fh, ensure_ascii=False)
    fh.write("\n")
os.replace(tmp, path)
PY
}

stop_instance() {
  local h=$1 p=$2 pids attempt
  pids=$(listener_pids "$p")
  if [ -z "$pids" ]; then
    echo "start: $h:$p 上有工作台，但查不到进程号（需要 ss / lsof / fuser）；请手动停止" >&2
    return 1
  fi
  echo "start: 停止旧实例 pid ${pids// /, }（端口 $p）" >&2
  # SIGTERM takes server.py's Ctrl-C path: running jobs are stopped, not orphaned.
  kill -TERM $pids 2>/dev/null || true
  for ((attempt = 0; attempt < 40; attempt++)); do
    if port_free "$h" "$p"; then
      echo "start: 旧实例已退出" >&2
      return 0
    fi
    sleep 0.25
  done
  echo "start: 10 秒内端口没释放，强制结束 pid ${pids// /, }" >&2
  kill -KILL $pids 2>/dev/null || true
  for ((attempt = 0; attempt < 20; attempt++)); do
    port_free "$h" "$p" && return 0
    sleep 0.25
  done
  echo "start: 端口 $p 仍被占用" >&2
  return 1
}

# Collect every workbench we might have to replace: the requested port, the
# one recorded last time, and the default port when asked for another one.
found=()
add_found() {
  local candidate="$1 $2" existing
  for existing in "${found[@]+"${found[@]}"}"; do
    [ "$existing" = "$candidate" ] && return 0
  done
  found+=("$candidate")
}

if probe "$host" "$port"; then add_found "$host" "$port"; fi
if read_state && probe "$state_host" "$state_port"; then add_found "$state_host" "$state_port"; fi
if [ "$port" -ne "$DEFAULT_PORT" ] && probe 127.0.0.1 "$DEFAULT_PORT"; then
  add_found 127.0.0.1 "$DEFAULT_PORT"
fi

if [ "${#found[@]}" -gt 0 ] && [ "$reuse" -eq 1 ]; then
  first="${found[0]}"
  announce_running "${first% *}" "${first#* }"
fi

if [ "${#found[@]}" -gt 0 ]; then
  running=0
  ports=""
  for entry in "${found[@]}"; do
    running=$((running + $(running_jobs "${entry% *}" "${entry#* }")))
    ports="$ports ${entry#* }"
  done
  if [ "$running" -gt 0 ] && [ "$force" -eq 0 ]; then
    echo "start: 端口$ports 上还有 $running 个任务在跑；加 --force 会中断它们，或先在页面里停止" >&2
    exit 1
  fi
  for entry in "${found[@]}"; do
    stop_instance "${entry% *}" "${entry#* }" || exit 1
  done
fi

if ! port_free "$host" "$port"; then
  if [ "$port_given" -eq 1 ]; then
    echo "start: $host:$port 已被其他服务占用；换一个端口：./start.sh --port $((port + 1))" >&2
    exit 1
  fi
  for ((candidate = port + 1; candidate <= port + 20; candidate++)); do
    if port_free "$host" "$candidate"; then
      echo "start: $host:$port 已被其他服务占用，改用 $candidate" >&2
      port=$candidate
      break
    fi
  done
fi

write_state "$host" "$port"
run_args=(--port "$port")
if [ "$host_given" -eq 1 ]; then run_args+=(--host "$host"); fi
if [ "${#extra[@]}" -gt 0 ]; then run_args+=("${extra[@]}"); fi
exec "$PY" -u "$SERVER" "${run_args[@]}"
