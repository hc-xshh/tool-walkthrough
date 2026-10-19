# Scripts

| Script | Purpose |
|---|---|
| `../../harness/preflight.sh` | Check display, app version, sandbox mode, CDP port, disk, login state |
| `../../harness/desktop-up.sh` | Xvfb + openbox + private DBus |
| `../../harness/app-launch.sh` | Launch a GUI app in the isolated desktop |
| `../../harness/cdp.py` | Electron/WebView driver: text / eval / click / clickel --nth / shot |
| `../../harness/shot.sh` | X11 screenshot |
| `../../harness/ocr.sh` | OCR word boxes (fallback) |
| `../../harness/build-report.py` | markdown → PDF (intermediate HTML stays in tmp) |

Typical sequence:

```bash
./harness/preflight.sh --app <name> --display :98 --port 9339
./harness/desktop-up.sh :98 1440x900x24
# launch Electron with --no-sandbox --remote-debugging-port=9339
./harness/cdp.py --port 9339 text
```
