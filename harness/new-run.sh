#!/usr/bin/env bash
# Create a local-only run directory. Evidence under runs/ is never committed.
# Usage: ./harness/new-run.sh <YYYY-MM-DD>-<tool>
#
# Thin wrapper: the real scaffolding lives in wt.py so shell and Python users
# get the same layout (shots/logs/trace/artifacts + copied templates).
set -euo pipefail

name="${1:-}"
if [ -z "$name" ]; then
  echo "usage: $0 <YYYY-MM-DD>-<tool>" >&2
  exit 2
fi

root="$(git rev-parse --show-toplevel)"
cd "$root"
exec python3 harness/wt.py new-run "$name"
