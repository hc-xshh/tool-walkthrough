#!/usr/bin/env bash
# Install local git hooks that keep evidence and PII out of the public repo.
# Run once per clone: ./harness/install-git-hooks.sh
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
hooks_dir="$(git rev-parse --git-dir)/hooks"
terms="$(git rev-parse --git-dir)/pii-terms"

install -m 755 harness/git-hooks/pre-commit "$hooks_dir/pre-commit"
install -m 755 harness/git-hooks/pre-push "$hooks_dir/pre-push"

if [ ! -f "$terms" ]; then
  cat > "$terms" <<'EOF'
# Local-only blocklist read by pre-commit / pre-push.
# One term per line. Never commit this file (it lives inside .git/).
# Add your account handle, email address, and local username, for example:
# your-handle
# <your-email>
EOF
fi

echo "installed: $hooks_dir/pre-commit"
echo "installed: $hooks_dir/pre-push"
echo "terms:     $terms (local only)"
echo "Add your own terms to the file above, then test with a fake commit."
