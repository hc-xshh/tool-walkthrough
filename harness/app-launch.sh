#!/usr/bin/env bash
# Launch a GUI app inside the isolated desktop.
# Usage: app-launch.sh <app-path> [args...]
#
# Default: fresh isolated HOME (first-run experience).
# To test a logged-in tool, set WALKTHROUGH_HOME=/home/<you> and WALKTHROUGH_DBUS=unix:path=/run/user/<uid>/bus.
# Software GL is on by default here (Xvfb has no GPU); set WALKTHROUGH_SOFTWARE_GL=0
# when launching on a real desktop where smoothness matters.
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $0 <app-path> [args...]" >&2
  exit 2
fi

APP="$1"
shift

DISP="${WALKTHROUGH_DISPLAY:-:98}"
BASE="${WALKTHROUGH_BASE:-/tmp/walkthrough}"
HOME_DIR="${WALKTHROUGH_HOME:-$BASE/home}"
DBUS_ADDR="${WALKTHROUGH_DBUS:-unix:path=$BASE/runtime/bus}"
LOG="${WALKTHROUGH_LOG:-$BASE/app.log}"
SOFT_GL="${WALKTHROUGH_SOFTWARE_GL:-1}"

# Refuse early instead of reporting "launched" for a path that cannot run.
if ! command -v "$APP" >/dev/null 2>&1 && [ ! -x "$APP" ]; then
  echo "not executable: $APP" >&2
  exit 2
fi

mkdir -p "$HOME_DIR" "$BASE/runtime" "$(dirname "$LOG")"

gl_env=(GDK_BACKEND=x11)
if [ "$SOFT_GL" != "0" ]; then
  gl_env+=(LIBGL_ALWAYS_SOFTWARE=1 WEBKIT_DISABLE_COMPOSITING_MODE=1 WEBKIT_DISABLE_DMABUF_RENDERER=1)
fi

env DISPLAY="$DISP" \
    HOME="$HOME_DIR" \
    XDG_RUNTIME_DIR="$BASE/runtime" \
    DBUS_SESSION_BUS_ADDRESS="$DBUS_ADDR" \
    "${gl_env[@]}" \
    "$APP" "$@" >"$LOG" 2>&1 &

PID=$!
sleep 0.3
if ! kill -0 "$PID" 2>/dev/null; then
  echo "exited immediately; see $LOG:" >&2
  tail -n 5 "$LOG" >&2 || true
  exit 1
fi

echo "launched pid $PID log=$LOG"
echo "display=$DISP home=$HOME_DIR"
