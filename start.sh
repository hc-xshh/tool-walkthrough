#!/usr/bin/env bash
# Start — or reuse — the walkthrough workbench: the local page that configures
# the model, launches walkthrough / eval runs, and streams logs and artifacts.
#
#   ./start.sh                  # reuse a running workbench, else start on 8790
#   ./start.sh --port 8791      # reuse the workbench on 8791, else start there
#   ./start.sh --host 127.0.0.1 # passed through to server.py
#
# Idempotent: a second run never starts a second instance. It looks for the
# workbench recorded in runs/workbench/server.json, or one already answering on
# the requested port (server.py identifies itself with a Server header), prints
# the URL and exits 0. Only when none is found does it start one.
#
# Windows: python workbench\server.py
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
SERVER="$ROOT/workbench/server.py"
STATE="$ROOT/runs/workbench/server.json"
DEFAULT_PORT=8790

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

# --help belongs to the server; never pre-empt it.
for arg in "$@"; do
  case "$arg" in
    -h|--help) exec "$PY" -u "$SERVER" "$@" ;;
  esac
done

# Read --port / --host without consuming them, so "$@" stays intact for exec.
args=("$@")
port=$DEFAULT_PORT
host=127.0.0.1
port_given=0
i=0
while [ "$i" -lt "${#args[@]}" ]; do
  arg="${args[$i]}"
  case "$arg" in
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
      i=$((i + 2))
      ;;
    --host=*)
      host="${arg#*=}"
      i=$((i + 1))
      ;;
    *) i=$((i + 1)) ;;
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
try:
    with socket.socket() as sock:
        sock.bind((host, port))
except OSError:
    sys.exit(1)
PY
}

announce_running() {
  echo "start: 工作台已在运行 → http://$1:$2/"
  echo "start: 没有重复启动；要重启先停掉那个进程（Ctrl-C）"
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

# 1. Reuse anything already answering on the requested address.
if probe "$host" "$port"; then
  write_state "$host" "$port"
  announce_running "$host" "$port"
fi

# 2. With no --port, honor the instance recorded by a previous run, wherever
#    it ended up (the default port may be taken by an unrelated service).
if [ "$port_given" -eq 0 ]; then
  if read_state && probe "$state_host" "$state_port"; then
    write_state "$state_host" "$state_port"
    announce_running "$state_host" "$state_port"
  fi
fi

if ! port_free "$host" "$port"; then
  if [ "$port_given" -eq 1 ]; then
    echo "start: $host:$port 已被其他服务占用；换一个端口：./start.sh --port $((port + 1))" >&2
    exit 1
  fi
  # Scan upward: reuse a workbench found on the way (a fallback port from an
  # earlier run), otherwise take the first free port.
  for ((candidate = port + 1; candidate <= port + 20; candidate++)); do
    if probe "$host" "$candidate"; then
      write_state "$host" "$candidate"
      announce_running "$host" "$candidate"
    fi
    if port_free "$host" "$candidate"; then
      echo "start: $host:$port 已被其他服务占用，改用 $candidate" >&2
      write_state "$host" "$candidate"
      exec "$PY" -u "$SERVER" --port "$candidate" "$@"
    fi
  done
  echo "start: $host:$port 起连续 20 个端口都被占用" >&2
  exit 1
fi

write_state "$host" "$port"
exec "$PY" -u "$SERVER" "$@"
