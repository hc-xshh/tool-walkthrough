#!/usr/bin/env bash
# Start an isolated X11 desktop for UI walkthroughs.
# Usage: desktop-up.sh [DISPLAY] [GEOMETRY]
#   DISPLAY  default :98
#   GEOMETRY default 1440x900x24
set -euo pipefail

DISP="${1:-:98}"
GEOM="${2:-1440x900x24}"
BASE="${WALKTHROUGH_BASE:-/tmp/walkthrough}"
mkdir -p "$BASE/home" "$BASE/runtime"
chmod 700 "$BASE/runtime"

# 1. X server
if ! xdpyinfo -display "$DISP" >/dev/null 2>&1; then
  Xvfb "$DISP" -screen 0 "$GEOM" -nolisten tcp >"$BASE/xvfb.log" 2>&1 &
  echo $! >"$BASE/xvfb.pid"
  sleep 2
fi

# 2. window manager (per-display pid file, avoids clobbering the real desktop's WM)
if [ -f "$BASE/openbox.pid" ] && kill -0 "$(cat "$BASE/openbox.pid")" 2>/dev/null; then
  :
else
  DISPLAY="$DISP" openbox --sm-disable >"$BASE/wm.log" 2>&1 &
  echo $! >"$BASE/openbox.pid"
fi

# 3. private session bus (isolates single-instance locks from the real desktop)
if [ ! -S "$BASE/runtime/bus" ]; then
  dbus-daemon --session --address="unix:path=$BASE/runtime/bus" \
    --fork --print-address >"$BASE/dbus.addr" 2>&1
  sleep 1
fi

echo "display=$DISP geometry=$GEOM base=$BASE"
echo "dbus=unix:path=$BASE/runtime/bus"
