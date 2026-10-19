# 安装与排错

Linux 已实测（Ubuntu 22.04 / 24.04 / 26.04）；macOS 与 Windows 的 `wt.py` 分支已实现，但尚未在真机实测，第一次用先跑预检。

三平台都需要：Python 3.9+、tesseract（含 `chi_sim`）、Chrome/Chromium，以及 `harness/requirements.txt` 里的三个包。

## 1. Linux（Ubuntu / Debian）

```bash
sudo apt-get update
sudo apt-get install -y \
  xvfb openbox dbus-x11 x11-utils xdotool \
  ffmpeg tesseract-ocr tesseract-ocr-chi-sim \
  fonts-noto-cjk \
  python3-gi gir1.2-gtk-3.0 \
  chromium-browser
```

- `python3-gi` / `gir1.2-gtk-3.0` 只在用 `portal-shot.py`（GNOME Wayland 整屏截图）时需要。
- `chromium-browser` 用于出 PDF；已装 Google Chrome 可跳过，脚本会自动找。
- 其他发行版换成对应包管理器；核心依赖是 Xvfb、openbox、dbus、ffmpeg、xdotool、tesseract。

## 2. macOS

```bash
brew install tesseract tesseract-lang cliclick
```

- `tesseract-lang` 包含 `chi_sim`；`cliclick` 用于坐标点击，没装时 `wt.py` 会退回 AppleScript。
- 截图用系统自带的 `screencapture`，不需要额外安装。
- 安装 Chrome 或 Chromium 用于出 PDF；Edge 也可作为兜底。
- **权限**：系统设置 → 隐私与安全性 → 给 Terminal / agent 进程开 **屏幕录制** 和 **辅助功能**；否则截图黑屏、点击无效。
- **隔离**：不要用主力账号直接跑。新建一个 macOS 用户，或用虚拟机；`HOME` 覆盖在 macOS 上不可靠，不建议用。
- Apple Silicon 与 Intel 都用系统 Python 3 或 `brew install python`。

## 3. Windows

1. 安装 **Python 3.9+**（python.org，勾选 Add to PATH）。
2. 安装 **Git for Windows**（提供 Git Bash，钩子脚本要用）。
3. 安装 **Tesseract**（UB Mannheim 安装包），勾选 `chi_sim` 语言数据，并把安装目录加入 PATH。
4. 安装 **Chrome / Chromium / Edge** 之一。
5. 用 PowerShell 或 CMD 在**交互式桌面会话**里运行；服务账号的 session 0 截不到界面。

```powershell
py -3 harness\wt.py preflight
py -3 harness\wt.py shot shots\01.png
```

- 截图走 PowerShell + .NET，点击走 `ctypes` 调 user32，不需要额外工具。
- 不能从非提权进程点击提权窗口（UAC 隔离）；被测应用是管理员权限时，agent 也要用管理员权限启动。
- 隔离：新建一个 Windows 用户，或使用虚拟机；不要在日常账号的桌面上做破坏性操作。

## 4. Python 依赖

```bash
python3 -m pip install -r harness/requirements.txt
# Windows: py -3 -m pip install -r harness\requirements.txt
```

或虚拟环境：

```bash
python3 -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r harness/requirements.txt
```

`portal-shot.py` 依赖系统 Python 的 `gi` 模块，Linux 上用 `/usr/bin/python3` 跑；`cdp.py`、`wt.py`、`build-report.py` 可以在 venv 里跑。

## 5. 自检

```bash
python3 harness/wt.py preflight
```

输出里 `FAIL` 需要处理，`WARN` 需要判断：

- `tesseract FAIL` → Linux 装 `tesseract-ocr-chi-sim`；macOS 装 `tesseract-lang`；Windows 把安装目录加进 PATH
- `chrome FAIL` → 装 Chrome / Chromium / Edge，或设 `WALKTHROUGH_CHROME`
- `display :98 FAIL`（仅 Linux）→ 先跑 `./harness/desktop-up.sh :98 1440x900x24`
- `cliclick WARN`（macOS）→ 可装可不装；不装则点坐标走 AppleScript
- macOS 权限没开 → 截图黑屏或点击无效，去“隐私与安全性”补

Linux 还可以跑 `bash harness/preflight.sh --app <name> --port 9339`，额外检查 deb 包、`chrome-sandbox` 权限、CDP 端口和登录态目录。

## 6. Git 钩子（公开仓必做）

macOS / Linux：

```bash
bash harness/install-git-hooks.sh
```

Windows：在 **Git Bash** 里执行同一条命令（Git for Windows 自带 `sh`、`cp`、`chmod`）。

然后把账号名、邮箱、本机用户名写进本地黑名单（只存在 `.git/`，不会提交）：

```bash
cat >> .git/pii-terms <<'EOF'
your-handle
<your-email>
EOF
```

钩子会拦 `runs/`、图片 / PDF / 日志 / docx / zip、邮箱、`/home/<user>`、飞书文档链接、`machine_id` 参数，以及 `.git/pii-terms` 里的自定义词。它防手滑，不防 `--no-verify`。

## 7. 常见问题

**截图全黑 / 窗口不可见**
- Linux：Xvfb 只认 X11；在真实 Wayland 会话里 Electron 要加 `--ozone-platform=wayland`，在 Xvfb 里相反，`env -u WAYLAND_DISPLAY DISPLAY=:98` 启动。
- macOS：没给屏幕录制权限。
- Windows：不在交互式桌面会话，或目标窗口在另一个虚拟桌面。

**点击没反应**
- macOS：没给辅助功能权限；或坐标是 Retina 逻辑坐标与物理像素不一致（`screencapture` 输出是物理像素，`cliclick` 用逻辑点，按比例换算）。
- Windows：被测窗口是管理员权限，agent 不是。
- Linux：Wayland 下 `xdotool` 注入可能无效，改用 CDP 或 X11 会话。

**CDP 连接 403 `Rejected an incoming WebSocket connection`**
Chromium 拒绝默认 Origin。`cdp.py` 已用 `suppress_origin=True`；自己写客户端时同样处理，或启动加 `--remote-allow-origins=*`。

**同一个 HOME / 同一账号起不来第二个实例**
单实例锁。先关掉真实桌面上的实例，或在隔离用户 / 隔离 HOME 里起。

**tesseract 中文乱码**
确认 `chi_sim` 数据已安装，并用 `--lang chi_sim+eng`。

**PDF 中文变方框**
装 Noto Sans CJK（Linux `fonts-noto-cjk`，macOS `brew install --cask font-noto-sans-cjk`，Windows 装 Noto Sans SC）。`build-report.py` 的字体栈以 `Noto Sans CJK SC` 开头，找不到时会退回系统字体。

**portal 截图一直等（仅 Linux GNOME）**
首次调用需要用户在桌面上点「允许」。`parent_window` 传空字符串，不要传 `x11:<id>`（会卡住）。
