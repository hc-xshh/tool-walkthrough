# 安装与排错

在 Ubuntu 22.04 / 24.04 / 26.04 上验证。其他发行版把 `apt` 换成对应包管理器即可，脚本本身是 bash + Python，不依赖 Ubuntu 特有工具。

## 1. 系统依赖

```bash
sudo apt-get update
sudo apt-get install -y \
  xvfb openbox dbus-x11 x11-utils xdotool \
  ffmpeg tesseract-ocr tesseract-ocr-chi-sim \
  fonts-noto-cjk \
  python3-gi gir1.2-gtk-3.0 \
  chromium-browser
```

`gir1.2-gtk-3.0` 与 `python3-gi` 只在使用 `portal-shot.py`（GNOME Wayland 整屏截图）时需要。
`chromium-browser` 用于 `build-report.py` 出 PDF；已装 Google Chrome 时可跳过，脚本会依次找 `google-chrome`、`chromium`，也可用 `WALKTHROUGH_CHROME` 指定。

## 2. Python 依赖

```bash
python3 -m pip install -r harness/requirements.txt
```

或使用虚拟环境：

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r harness/requirements.txt
```

注意：`portal-shot.py` 依赖系统 Python 的 `gi` 模块，**用 `/usr/bin/python3` 跑**；`cdp.py` 与 `build-report.py` 可以在 venv 里跑。

## 3. 自检

```bash
bash harness/preflight.sh --display :98 --app <package-or-binary> --port 9339
```

输出里 `FAIL` 需要处理，`WARN` 需要判断：

- `display :98 FAIL` → 先跑 `./harness/desktop-up.sh :98 1440x900x24`
- `host dependencies WARN` → 第 1 步有包没装
- `chrome-sandbox WARN` → 权限不是 `4755`；先加 `--no-sandbox` 启动并实测，不要直接判定产品缺陷
- `CDP WARN` → 应用还没带 `--remote-debugging-port` 启动
- `disk $HOME FAIL` → 至少留 5 GB（安装包 + 截图）

## 4. 常见问题

**应用起来了但截图全黑 / 窗口不可见**
Xvfb 里只认 X11。Electron 在真实 Wayland 会话里要加 `--ozone-platform=wayland`；在 Xvfb 里相反，`env -u WAYLAND_DISPLAY DISPLAY=:98` 启动即可。GTK / WebKitGTK 应用需要 `GDK_BACKEND=x11`（`app-launch.sh` 已设）。

**CDP 连接 403 `Rejected an incoming WebSocket connection`**
Chromium 拒绝默认 Origin。`cdp.py` 已用 `suppress_origin=True`；自己写客户端时同样处理，或启动加 `--remote-allow-origins=*`。

**同一个 HOME 起不来第二个实例**
单实例锁。先关掉真实桌面上的实例，或在隔离 HOME 里起。

**tesseract 中文乱码**
确认装了 `tesseract-ocr-chi-sim`，并用 `ocr.sh image.png chi_sim+eng`。

**PDF 中文变方框**
装 `fonts-noto-cjk`；`build-report.py` 的字体栈是 `Noto Sans CJK SC`。

**portal 截图一直等**
首次调用需要用户在桌面上点「允许」。`parent_window` 传空字符串，不要传 `x11:<id>`（会卡住）。
