# Tool Walkthrough — AI 工具体验走查方法包

一套可复用的「AI 工具 / 桌面应用」体验走查方法：**任务驱动的流程 + 隔离桌面 harness + 报告标准**。

> 回答的不是「界面好不好看」，而是一个决策问题：**这个版本能不能上、能不能推给团队、上线前先修哪三件。**
> n=1 是探索性观察，不外推；报告是决策材料，不是过程记录。

## 包里有什么

| 路径 | 内容 |
|---|---|
| `METHOD.md` | 方法本体：6 步流程、任务设计、0–4 严重度、发现写法、报告结构、质量清单 |
| `templates/tool-profile.md` | 走查前的工具调研模板（事实卡 + 官方声明表） |
| `templates/task-plan.md` | 任务矩阵模板（任务 / 成功标准 / 结果 / 证据） |
| `templates/report.md` | 六节报告模板 |
| `harness/` | 可执行工具：隔离 X11 桌面、CDP 驱动、截图 / OCR / 点击、整屏 portal 截图、PDF 出片、预检 |
| `walkthrough-harness/` | 借鉴 Harness² 的 8 组件骨架（system prompt / guardrails / memory / tool guidance / skills / subagents / scripts / plugins） |

## 不包含什么

- **不含 `runs/` 案例库**：报告、截图、日志、产物都不在本包内。方法可以独立使用；需要样本时按本包流程自己跑一轮。
- `runs/` 默认写在 `.gitignore` 里：证据常含账号、桌面和登录态，是否入库由你决定。
- **不含任何被测产品的账号、登录态、截图或原始日志**。
- 不包含 AI 编程工具的代码能力评测方法（那是另一套：同一任务书 + 独立验收脚本判分）。

## 依赖

Linux（Ubuntu 22.04+ 实测）。需要 Xvfb、openbox、dbus、ffmpeg、xdotool、tesseract、Chrome/Chromium、Python 3 与三个 pip 包。

完整安装命令与排错见 [`INSTALL.md`](INSTALL.md)。

## 快速开始

```bash
# 0. 先做工具调研（20–30 分钟，只读文档，不预演界面）
#    产出 runs/<date>-<tool>/tool-profile.md；模板 templates/tool-profile.md
#    来源优先级与 8 项清单见 METHOD.md 的 Step 0

# 1. 起隔离桌面（默认 :98）
./harness/desktop-up.sh :98 1440x900x24
./harness/preflight.sh --display :98 --app <package-or-binary> --port 9339

# 2. 启动应用。默认用全新 HOME（首次体验）；
#    需要登录态时：WALKTHROUGH_HOME=$HOME WALKTHROUGH_DBUS=unix:path=/run/user/$(id -u)/bus
./harness/app-launch.sh /usr/bin/<app>

# 3. 原生 GUI：截图 / OCR 找坐标 / 点击
./harness/shot.sh /tmp/walkthrough/01.png
./harness/ocr.sh /tmp/walkthrough/01.png
./harness/click.sh 300 241

# 4. Electron / WebView：CDP 读 DOM、按文字点、截渲染层
#    启动时加 --remote-debugging-port=9339
python3 harness/cdp.py text
python3 harness/cdp.py clicktext "登录"
python3 harness/cdp.py clickel "允许读取" --nth 0   # 选项带序号时按第 n 个匹配点
python3 harness/cdp.py shot /tmp/walkthrough/02.png

# 5. GNOME Wayland 整屏 / 原生弹窗（可选，需要用户授权一次）
/usr/bin/python3 harness/portal-shot.py --out /tmp/walkthrough/full.png

# 6. 出 PDF（中间 HTML 只写临时目录）
./harness/build-report.py runs/<date>-<tool>
```

## 适配点

- `preflight.sh --app <name>`：包名或可执行文件名；`--sandbox <path>` 指定 Electron 的 `chrome-sandbox`；`--home-dir <path>` 指定已有登录态目录。不传时会在 `/opt` 与 `$HOME` 下找候选，只报 WARN，不阻断。
- 环境变量：`WALKTHROUGH_DISPLAY`（默认 `:98`）、`WALKTHROUGH_BASE`（默认 `/tmp/walkthrough`）、`WALKTHROUGH_HOME`、`WALKTHROUGH_DBUS`、`WALKTHROUGH_LOG`、`WALKTHROUGH_CHROME`（出 PDF 用的浏览器）。
- `desktop-up.sh` 只负责 Xvfb + openbox + 私有 session bus；portal 截图走的是真实桌面会话，两者不要混着取证。

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
