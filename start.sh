#!/usr/bin/env bash
# Start the walkthrough workbench: the local page that configures the model,
# launches walkthrough / eval runs, and streams their logs and artifacts.
#
#   ./start.sh                  # http://127.0.0.1:8790/ (next free port if busy)
#   ./start.sh --port 8791      # pin the port; fails loudly if it is taken
#   ./start.sh --host 127.0.0.1 # loopback only, --host is passed through
#
# Whatever the script does not consume is handed to workbench/server.py, so
# `./start.sh --help` shows the server's own options.
#
# Windows: python workbench\server.py
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
SERVER="$ROOT/workbench/server.py"

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
port=8790
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

# A bind test is enough: the server itself has no busy-port fallback.
port_free() {
  "$PY" - "$host" "$1" <<'PY'
import socket, sys

host, port = sys.argv[1], int(sys.argv[2])
try:
    with socket.socket() as sock:
        sock.bind((host, port))
except OSError:
    sys.exit(1)
PY
}

if ! port_free "$port"; then
  if [ "$port_given" -eq 1 ]; then
    echo "start: $host:$port 已被占用；换一个端口：./start.sh --port $((port + 1))" >&2
    exit 1
  fi
  # No --port was given, so "$@" carries nothing to strip: just add the one
  # we picked.
  for ((candidate = port + 1; candidate <= port + 20; candidate++)); do
    if port_free "$candidate"; then
      echo "start: $host:$port 已被占用，改用 $candidate" >&2
      exec "$PY" -u "$SERVER" --port "$candidate" "$@"
    fi
  done
  echo "start: $host:$port 起连续 20 个端口都被占用" >&2
  exit 1
fi

exec "$PY" -u "$SERVER" "$@"
