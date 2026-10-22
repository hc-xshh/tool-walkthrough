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

fail() { echo "desktop-up: $*" >&2; exit 1; }

# 1. X server
if ! xdpyinfo -display "$DISP" >/dev/null 2>&1; then
  # a stale socket from a crashed Xvfb blocks the display, so clear it first
  rm -f "/tmp/.X${DISP#:}-lock" "/tmp/.X11-unix/X${DISP#:}" 2>/dev/null || true
  Xvfb "$DISP" -screen 0 "$GEOM" -nolisten tcp >"$BASE/xvfb.log" 2>&1 &
  echo $! >"$BASE/xvfb.pid"
  for _ in $(seq 1 20); do
    xdpyinfo -display "$DISP" >/dev/null 2>&1 && break
    sleep 0.5
  done
  xdpyinfo -display "$DISP" >/dev/null 2>&1 \
    || fail "Xvfb did not come up on $DISP (see $BASE/xvfb.log)"
fi

# 2. window manager (per-display pid file, avoids clobbering the real desktop's WM)
WM_PID="$BASE/openbox-$DISP.pid"
if [ -f "$WM_PID" ] && kill -0 "$(cat "$WM_PID")" 2>/dev/null; then
  :
else
  DISPLAY="$DISP" openbox --sm-disable >"$BASE/wm.log" 2>&1 &
  echo $! >"$WM_PID"
  sleep 1
  kill -0 "$(cat "$WM_PID")" 2>/dev/null || fail "openbox failed (see $BASE/wm.log)"
fi

# 3. private session bus (isolates single-instance locks from the real desktop)
if [ ! -S "$BASE/runtime/bus" ]; then
  dbus-daemon --session --address="unix:path=$BASE/runtime/bus" \
    --fork --print-address >"$BASE/dbus.addr" 2>&1 \
    || fail "dbus-daemon failed (see $BASE/dbus.addr)"
  sleep 1
fi
[ -S "$BASE/runtime/bus" ] || fail "session bus socket missing: $BASE/runtime/bus"

echo "display=$DISP geometry=$GEOM base=$BASE"
echo "dbus=unix:path=$BASE/runtime/bus"
