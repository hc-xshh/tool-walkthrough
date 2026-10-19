# Tool Walkthrough — AI 工具体验走查方法包

一套可复用的「AI 工具 / 桌面应用」体验走查方法：**任务驱动的流程 + 隔离桌面 harness + 报告标准**。

当前方法版本：**v3**（变更见 [`CHANGELOG.md`](CHANGELOG.md)）。

> 回答的不是「界面好不好看」，而是一个决策问题：**这个版本能不能上、能不能推给团队、上线前先修哪三件。**
> n=1 是探索性观察，不外推；报告是决策材料，不是过程记录。

## 包里有什么

| 路径 | 内容 |
|---|---|
| `METHOD.md` | 方法本体：6 步流程、任务设计、0–4 严重度、发现写法、报告结构、质量清单 |
| `templates/tool-profile.md` | 走查前的工具调研模板（事实卡 + 官方声明表） |
| `templates/task-plan.md` | 任务矩阵模板（任务 / 成功标准 / 结果 / 证据） |
| `templates/report.md` | 六节报告模板 |
| `harness/` | 跨平台入口 `wt.py`（截图 / 点击 / OCR / 启动 / 出片 / 预检）+ Linux 隔离桌面脚本 + CDP 驱动 |
| `walkthrough-harness/` | 借鉴 Harness² 的 8 组件骨架（system prompt / guardrails / memory / tool guidance / skills / subagents / scripts / plugins） |

## 不包含什么

- **不含 `runs/` 案例库**：报告、截图、日志、产物都不在本包内。方法可以独立使用；需要样本时按本包流程自己跑一轮。
- `runs/` 默认写在 `.gitignore` 里：证据常含账号、桌面和登录态，是否入库由你决定。
- **不含任何被测产品的账号、登录态、截图或原始日志**。
- 不包含 AI 编程工具的代码能力评测方法（那是另一套：同一任务书 + 独立验收脚本判分）。

## 依赖

Linux / macOS / Windows 都能跑；Linux 最完整，macOS 与 Windows 用 `wt.py` 走原生截图 / 点击，隔离靠独立用户或虚拟机。

需要：Python 3.9+、tesseract（含 `chi_sim`）、Chrome/Chromium，以及三个 pip 包。Linux 额外需要 Xvfb、openbox、dbus、ffmpeg、xdotool。

完整安装命令与排错见 [`INSTALL.md`](INSTALL.md)。

## 快速开始

```bash
# 0. 先做工具调研（20–30 分钟，只读文档，不预演界面）
#    产出 runs/<date>-<tool>/tool-profile.md；模板 templates/tool-profile.md
#    来源优先级与 8 项清单见 METHOD.md 的 Step 0

# 1. 建本轮目录（三平台）
python3 harness/wt.py new-run 2026-10-19-<tool>

# 2. 预检（三平台）
python3 harness/wt.py preflight

# 3. 启动应用
#    Linux：默认全新 HOME；需要登录态时设 WALKTHROUGH_HOME / WALKTHROUGH_DBUS
python3 harness/wt.py launch --log runs/<run>/logs/app.log -- /usr/bin/<app>
#    macOS：--app 走 `open -a`；Windows：直接传 exe 路径
python3 harness/wt.py launch --app "<AppName>" --log runs/<run>/logs/app.log

# 4. 原生 GUI：截图 / OCR 找坐标 / 点击（三平台）
python3 harness/wt.py shot runs/<run>/shots/01.png
python3 harness/wt.py ocr runs/<run>/shots/01.png
python3 harness/wt.py click 300 241

# 5. Electron / WebView：CDP 读 DOM、按文字点、截渲染层
#    启动时加 --remote-debugging-port=9339
python3 harness/cdp.py text
python3 harness/cdp.py clicktext "登录"
python3 harness/cdp.py clickel "允许读取" --nth 0   # 选项带序号时按第 n 个匹配点
python3 harness/cdp.py shot runs/<run>/shots/02.png

# 6. 出 PDF（中间 HTML 只写临时目录）
python3 harness/wt.py report runs/<date>-<tool>

# Linux 隔离桌面（可选；macOS / Windows 用独立用户或虚拟机）
./harness/desktop-up.sh :98 1440x900x24
```

> macOS / Windows 分支已经实现，但尚未在真机实测；第一次用先跑 `python3 harness/wt.py preflight`，按输出补依赖和权限。

## 日常工作流（单仓）

公开仓同时是工作区；报告、截图和日志只留在本地：

1. 建本轮目录：`python3 harness/wt.py new-run 2026-10-19-<tool>`
   （生成 `runs/<run>/{shots,logs,artifacts}`）
2. 跑走查、写 `report.md`，产物放同一目录
3. 只提交方法 / 模板 / harness 的改动；`runs/` 已被 `.gitignore` 忽略
4. 首次 clone 后跑一次 `./harness/install-git-hooks.sh`

钩子会拦：`runs/` 路径、图片 / PDF / 日志 / docx / zip 等证据文件、邮箱、`/home/<user>`、飞书文档链接、`machine_id` 参数，以及 `.git/pii-terms` 里自己加的账号名。

不要 `git add -f runs/`，不要 `git clean -xdf`（会删掉未跟踪的证据）。

**备份**：`runs/` 只在本机，没有远程副本。换机、误删、硬盘故障都会丢；自己定期同步到外置盘或网盘。

## 跨平台对照

| 能力 | Linux | macOS | Windows |
|---|---|---|---|
| 截图 | `ffmpeg` x11grab | `screencapture` | PowerShell + .NET |
| 点击 | `xdotool` | `cliclick`，没有则 AppleScript | `ctypes`（user32） |
| OCR | tesseract | tesseract（brew） | tesseract（PATH） |
| Electron / CDP | `cdp.py` | `cdp.py` | `cdp.py` |
| 隔离 | Xvfb + 私有 DBus | 独立 macOS 用户或虚拟机 | 独立用户或虚拟机 |
| 出 PDF | Chrome / Chromium | Chrome / Chromium / Edge | Chrome / Chromium / Edge |
| Git 钩子 | bash | bash | Git Bash |

macOS 需要给终端 / agent 进程开 **屏幕录制** 和 **辅助功能**；Windows 需要在交互式桌面会话里跑，服务账号的 session 0 截不到界面。

## 适配点

- `python3 harness/wt.py preflight`：三平台统一预检（Python、tesseract、Chrome、截图/点击工具、Linux display）。
- `wt.py shot|click|ocr|launch|new-run|report`：三平台统一入口；命令参数放在 `--` 之后（`launch --log x -- /path/app`）。
- `preflight.sh`、`desktop-up.sh`、`app-launch.sh`、`shot.sh`、`click.sh`、`portal-shot.py` 是 Linux 原生脚本，保留兼容；跨平台优先用 `wt.py`。

## 方法要点

1. **先定决策问题**：谁读、要做什么决定、这次不回答什么。
2. **任务驱动，不按菜单逛**：5–8 个用户任务，覆盖首启、核心任务、产物取回、失败态、连续任务、设置。
3. **每条发现四件事**：具体元素 + 导致的后果 + 证据 + 建议；不写「用户找不到」。
4. **0–4 严重度**：4 阻断 / 3 严重 / 2 轻微 / 1 观感；S3/S4 必须人工复核，n=1 不写成功率。
5. **报告先给前三**，另有「做对了什么」，防止团队把没坏的部分一起改。

## 边界（写进交付，不要省）

- 走查 agent 交的是「不疲劳的第一遍」候选问题，最终判定仍需人。
- n=1 是探索性观察，不外推到其他版本 / 环境；不写成功率。
- 单评分者（尤其 AI）严重度不可信；S3/S4 必须人工复核。
- 截图读屏得到的图标含义属于推断，标「推断」或「未核实」。
- 不把「发现的问题多」当质量信号；AI 会多报，也会有误报。
- 不能交：托盘 / 系统通知 / 文件选择器 / 拖拽 / 自启 / 自动更新 / 多显示器；Xvfb 下的性能与启动耗时；移动端；企业后台；真实扣费；服务端行为；动效细节。

## 来源与许可

- 方法参考 NN/g 的严重度与可执行发现、Maze / DHS 的报告结构、Builders Camp 的「前三 + 做对了什么 + backlog」，出处见 `METHOD.md` 第 13 节。
- `walkthrough-harness/` 只借鉴 Google Harness²（Apache-2.0）的组件划分，未复制其代码，也不跑其 benchmark。
- 本包以 MIT 许可发布，见 [`LICENSE`](LICENSE)。
