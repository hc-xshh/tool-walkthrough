#!/usr/bin/env bash
# Take a screenshot of the isolated desktop.
# Usage: shot.sh <out.png> [DISPLAY] [geometry]
set -euo pipefail
OUT="${1:?usage: shot.sh <out.png> [display] [geometry]}"
DISP="${2:-${WALKTHROUGH_DISPLAY:-:98}}"
GEOM="${3:-1440x900}"
mkdir -p "$(dirname "$OUT")"
DISPLAY="$DISP" ffmpeg -hide_banner -loglevel error \
  -f x11grab -video_size "$GEOM" -i "$DISP" -frames:v 1 -y "$OUT"
echo "$OUT"
