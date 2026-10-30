#!/usr/bin/env bash
# Click at screen coordinates on the real desktop via wt.py.
# Usage: click.sh <x> <y> [DISPLAY] [button]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
X="${1:?usage: click.sh <x> <y> [display] [button]}"
Y="${2:?usage: click.sh <x> <y> [display] [button]}"
DISP="${3:-${WALKTHROUGH_DISPLAY:-${DISPLAY:-:0}}}"
BTN="${4:-1}"
exec python3 "$ROOT/wt.py" --profile linux-desktop click "$X" "$Y" --display "$DISP" --button "$BTN"
