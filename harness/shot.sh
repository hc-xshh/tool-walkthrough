#!/usr/bin/env bash
# Take a screenshot of the real desktop via wt.py (portal on Wayland).
# Usage: shot.sh <out.png> [DISPLAY] [geometry]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:?usage: shot.sh <out.png> [display] [geometry]}"
DISP="${2:-${WALKTHROUGH_DISPLAY:-:0}}"
GEOM="${3:-}"
args=(--profile linux-desktop shot "$OUT" --display "$DISP")
[ -n "$GEOM" ] && args+=(--geometry "$GEOM")
exec python3 "$ROOT/wt.py" "${args[@]}"
