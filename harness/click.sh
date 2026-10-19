#!/usr/bin/env bash
# Click at screen coordinates on the isolated desktop.
# Usage: click.sh <x> <y> [DISPLAY] [button]
set -euo pipefail
X="${1:?usage: click.sh <x> <y> [display] [button]}"
Y="${2:?usage: click.sh <x> <y> [display] [button]}"
DISP="${3:-${WALKTHROUGH_DISPLAY:-:98}}"
BTN="${4:-1}"
DISPLAY="$DISP" xdotool mousemove "$X" "$Y" click "$BTN"
echo "clicked $X,$Y button=$BTN display=$DISP"
