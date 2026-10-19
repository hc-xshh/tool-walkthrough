#!/usr/bin/env bash
# Launch a GUI app inside the isolated desktop.
# Usage: app-launch.sh <app-path> [args...]
#
# Default: fresh isolated HOME (first-run experience).
# To test a logged-in tool, set WALKTHROUGH_HOME=/home/<you> and WALKTHROUGH_DBUS=unix:path=/run/user/<uid>/bus.
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $0 <app-path> [args...]" >&2
  exit 2
fi

DISP="${WALKTHROUGH_DISPLAY:-:98}"
BASE="${WALKTHROUGH_BASE:-/tmp/walkthrough}"
HOME_DIR="${WALKTHROUGH_HOME:-$BASE/home}"
DBUS_ADDR="${WALKTHROUGH_DBUS:-unix:path=$BASE/runtime/bus}"
LOG="${WALKTHROUGH_LOG:-$BASE/app.log}"

mkdir -p "$HOME_DIR"
env DISPLAY="$DISP" \
    HOME="$HOME_DIR" \
    XDG_RUNTIME_DIR="$BASE/runtime" \
    DBUS_SESSION_BUS_ADDRESS="$DBUS_ADDR" \
    GDK_BACKEND=x11 \
    LIBGL_ALWAYS_SOFTWARE=1 \
    WEBKIT_DISABLE_COMPOSITING_MODE=1 \
    WEBKIT_DISABLE_DMABUF_RENDERER=1 \
    "$@" >"$LOG" 2>&1 &

echo "launched pid $! log=$LOG"
echo "display=$DISP home=$HOME_DIR"
