# Scripts

| Script | Purpose |
|---|---|
| `../../harness/wt.py` | Cross-platform entry: preflight / new-run / shot / click / ocr / launch / report |
| `../../harness/preflight.sh` | Linux: display, app version, sandbox mode, CDP port, disk, login state |
| `../../harness/desktop-up.sh` | Linux: Xvfb + openbox + private DBus |
| `../../harness/app-launch.sh` | Linux: launch a GUI app in the isolated desktop |
| `../../harness/cdp.py` | Electron/WebView driver: text / eval / click / clickel --nth / shot (all OSes) |
| `../../harness/shot.sh` | Linux X11 screenshot |
| `../../harness/ocr.sh` | Linux OCR word boxes (fallback) |
| `../../harness/build-report.py` | markdown → PDF (intermediate HTML stays in tmp) |

Typical sequence (all platforms):

```bash
python3 harness/wt.py preflight
python3 harness/wt.py new-run 2026-10-19-<tool>
python3 harness/wt.py shot runs/<run>/shots/01.png
python3 harness/cdp.py --port 9339 text
python3 harness/wt.py report runs/<run>
```

Linux isolated desktop (optional):

```bash
./harness/desktop-up.sh :98 1440x900x24
```
