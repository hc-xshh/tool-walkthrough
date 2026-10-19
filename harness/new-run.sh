#!/usr/bin/env bash
# Create a local-only run directory. Evidence under runs/ is never committed.
# Usage: ./harness/new-run.sh <YYYY-MM-DD>-<tool>
set -euo pipefail

name="${1:-}"
if [ -z "$name" ]; then
  echo "usage: $0 <YYYY-MM-DD>-<tool>" >&2
  exit 2
fi

root="$(git rev-parse --show-toplevel)"
run="$root/runs/$name"
mkdir -p "$run/shots" "$run/logs" "$run/artifacts"

echo "$run"
echo "runs/ is git-ignored. Do not 'git add -f' this directory."
