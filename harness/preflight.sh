#!/usr/bin/env bash
# Preflight checks before a real-desktop walkthrough (active seated session).
# Usage: preflight.sh [--display :0] [--app <name>] [--port 9339]
#                     [--sandbox /path/to/chrome-sandbox] [--home-dir /path/to/login-state]
#
# Nothing here is tied to a specific product: pass --app, and optionally point
# --sandbox / --home-dir at the paths that apply to the tool under test.
set -uo pipefail

DISP="${DISPLAY:-:0}"
APP=""
PORT=""
SANDBOX=""
HOME_DIR=""

while [ $# -gt 0 ]; do
  case "$1" in
    --display) DISP="$2"; shift 2 ;;
    --app) APP="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --sandbox) SANDBOX="$2"; shift 2 ;;
    --home-dir) HOME_DIR="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

fail=0
say() { printf '%-28s %s\n' "$1" "$2"; }

# 0. host dependencies
missing=""
for bin in git ffmpeg xdotool tesseract; do
  command -v "$bin" >/dev/null 2>&1 || missing="$missing $bin"
done
if [ -z "$missing" ]; then
  say "host dependencies" "PASS"
else
  say "host dependencies" "WARN (missing:$missing; see INSTALL.md)"
fi

# 1. display
if xdpyinfo -display "$DISP" >/dev/null 2>&1; then
  say "display $DISP" "PASS"
else
  say "display $DISP" "FAIL (start a real desktop session, or export DISPLAY/XAUTHORITY)"; fail=1
fi

# 1b. logind: display :0 is not enough; require an active seated session.
if command -v loginctl >/dev/null 2>&1; then
  sid="${XDG_SESSION_ID:-}"
  if [ -z "$sid" ]; then
    sid=$(loginctl list-sessions --no-legend 2>/dev/null | awk -v u="$(id -u)" '$2==u && $4!="-"{print $1; exit}')
  fi
  if [ -n "$sid" ]; then
    active=$(loginctl show-session "$sid" -p Active --value 2>/dev/null)
    seat=$(loginctl show-session "$sid" -p Seat --value 2>/dev/null)
    stype=$(loginctl show-session "$sid" -p Type --value 2>/dev/null)
    if [ "$active" = "yes" ] && [ -n "$seat" ] && [ "$seat" != "-" ]; then
      say "logind session" "PASS ($stype, $seat)"
      if [ "$stype" = "wayland" ]; then
        runtime="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
        wd="${WAYLAND_DISPLAY:-wayland-0}"
        if [ -S "$runtime/$wd" ]; then
          say "wayland socket" "PASS ($runtime/$wd)"
        else
          say "wayland socket" "FAIL ($runtime/$wd missing)"; fail=1
        fi
      fi
    else
      say "logind session" "FAIL (no active seated session)"; fail=1
    fi
  else
    say "logind session" "FAIL (no user session)"; fail=1
  fi
else
  say "logind session" "WARN (loginctl missing)"
fi

# 2. app package / binary
if [ -n "$APP" ]; then
  if dpkg-query -W -f='${Version}' "$APP" >/dev/null 2>&1; then
    say "$APP version" "PASS ($(dpkg-query -W -f='${Version}' "$APP"))"
  elif command -v "$APP" >/dev/null 2>&1; then
    say "$APP binary" "PASS ($(command -v "$APP"))"
  else
    say "$APP" "WARN (not found as package or on PATH)"
  fi
fi

# 3. Electron sandbox. A 755 chrome-sandbox makes some debs die with a SUID
#    sandbox FATAL; the same mode can still launch others. Test the app, do not
#    infer from a previous product.
if [ -z "$SANDBOX" ]; then
  SANDBOX=$(find /opt -maxdepth 4 -name chrome-sandbox -print -quit 2>/dev/null || true)
fi
if [ -n "$SANDBOX" ] && [ -e "$SANDBOX" ]; then
  mode=$(stat -c '%a %U:%G' "$SANDBOX" 2>/dev/null || echo "?")
  if [ "$(stat -c '%a' "$SANDBOX" 2>/dev/null || echo '?')" = "4755" ]; then
    say "chrome-sandbox" "PASS ($mode; $SANDBOX)"
  else
    say "chrome-sandbox" "WARN ($mode; $SANDBOX — try --no-sandbox, then test)"
  fi
else
  say "chrome-sandbox" "SKIP (not found; pass --sandbox)"
fi

# 4. CDP port (optional)
if [ -n "$PORT" ]; then
  if ss -ltn 2>/dev/null | grep -q ":$PORT "; then
    say "CDP :$PORT" "PASS"
  else
    say "CDP :$PORT" "WARN (not listening yet)"
  fi
fi

# 5. disk (downloads + screenshots; 5 GB is a practical floor)
avail=$(df -Pk "$HOME" | awk 'NR==2 {print int($4/1024)}')
if [ "${avail:-0}" -ge 5120 ]; then
  say "disk \$HOME" "PASS (${avail} MB free)"
else
  say "disk \$HOME" "FAIL (${avail:-0} MB free)"; fail=1
fi

# 6. login state candidates. Pass --home-dir when you already know the path;
#    otherwise look for a dot-directory matching the app name.
if [ -n "$HOME_DIR" ]; then
  if [ -e "$HOME_DIR" ]; then
    say "login state" "FOUND $HOME_DIR"
  else
    say "login state" "WARN ($HOME_DIR missing)"
  fi
elif [ -n "$APP" ]; then
  found=$(find "$HOME" -maxdepth 2 -type d -iname "*${APP}*" 2>/dev/null | head -5 | tr '\n' ' ')
  if [ -n "$found" ]; then
    say "login state" "CANDIDATES $found"
  else
    say "login state" "WARN (no candidate; may need login)"
  fi
fi

exit "$fail"
