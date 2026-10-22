# Scripts

| Script | Purpose |
|---|---|
| `../../harness/wt.py` | Cross-platform entry: preflight / profiles / new-run / shot / click / ocr / launch / report / audit / **coverage** |
| `../../harness/ui-map.py` | Enumerate a screen's controls over CDP into `ui-map.md` (per-screen section + nav edge) |
| `../../harness/shot-window.ps1` | Windows: capture one window instead of the whole desktop (logs a `shot-window` event) |
| `../../harness/preflight.sh` | Linux: display, app version, sandbox mode, CDP port, disk, login state |
| `../../harness/desktop-up.sh` | Linux: Xvfb + openbox + private DBus |
| `../../harness/app-launch.sh` | Linux: launch a GUI app in the isolated desktop |
| `../../harness/cdp.py` | Electron/WebView driver: text / eval / click / clickel --nth / shot (all OSes) |
| `../../harness/shot.sh` | Linux X11 screenshot |
| `../../harness/ocr.sh` | Linux OCR word boxes (fallback) |
| `../../harness/build-report.py` | markdown → PDF (intermediate HTML stays in tmp) |

Typical sequence (all platforms; `<profile>` is `linux-desktop` / `linux-x11` / `macos` / `windows` / `ci`, and `--profile` goes before the subcommand so `harness.json` records it):

```bash
python3 harness/wt.py profiles
python3 harness/wt.py --profile <profile> preflight
python3 harness/wt.py --profile <profile> new-run 2026-10-19-<tool>

# cdp.py only reads WALKTHROUGH_RUN; wt.py also uses it when --run is omitted
export WALKTHROUGH_RUN=runs/2026-10-19-<tool>
# Windows PowerShell: $env:WALKTHROUGH_RUN = "runs\2026-10-19-<tool>"

python3 harness/wt.py --run runs/<run> shot runs/<run>/shots/01.png
python3 harness/cdp.py --port 9339 text
python3 harness/wt.py report runs/<run>
python3 harness/wt.py audit --strict runs/<run>
```

Linux isolated desktop (optional):

```bash
./harness/desktop-up.sh :98 1440x900x24
```
