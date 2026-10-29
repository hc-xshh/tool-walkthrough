# Tool Walkthrough — AI 工具体验走查方法包

一套可复用的「AI 工具 / 桌面应用」体验走查方法：**任务驱动的流程 + 隔离桌面 harness + 报告标准**。

当前方法版本：**v6.11**（变更见 [`CHANGELOG.md`](CHANGELOG.md)；本轮体检见 [`AUDIT.md`](AUDIT.md)）。

> 回答的不是「界面好不好看」，而是：**这个工具在哪些地方让人做不成事、做错事；证据是什么，多严重，多可信。**
> n=1 是探索性观察，不外推；报告是问题清单，不是过程记录。读的人可以从清单里读出决定，但报告不替他下结论。

## 包里有什么

| 路径 | 内容 |
|---|---|
| `METHOD.md` | 方法本体：7 步流程（含页面地图）、任务设计、0–4 严重度、发现写法、报告结构、质量清单 |
| `templates/tool-profile.md` | 走查前的工具调研模板（事实卡 + 官方声明表） |
| `templates/ui-map.md` | 页面地图模板（控件清单 + 归属任务 / 不测原因） |
| `templates/task-plan.md` | 任务矩阵模板（任务 / 成功标准 / 覆盖控件 / 结果 / 证据） |
| `templates/task-trace.md` | 实景任务执行 trace 模板（项目 / prompt / 思考与工具调用 / 独立验证） |
| `templates/report.md` | 六节问题清单模板（问题总览 + 全量清单，图随问题） |
| `harness/` | 跨平台入口 `wt.py`（截图 / 点击 / OCR / 启动 / 出片 / 预检 / 覆盖检查）+ `ui-map.py` 控件枚举 + Linux 隔离桌面脚本 + CDP 驱动；`webapp_accept.mjs` 全栈验收（Node 20+，随机端口 + 全新 DB）；`llm_operator.py` 让自带 LLM key 的 operator 自己观察/操作被测产品；`report_share.py` 把 Markdown 出成单文件 HTML / PDF / 钉钉 MD |
| `verify_all.py` | 一条命令跑完整健康检查：单元测试、任务规格、两个自测、Node 语法、Python 编译 |
| `code-eval/` | 编码能力判分（实验）：12 档 + L4b 对照 + 2 个完整项目 = 15 个任务（Python + 一个 Node.js 并发任务，含一个真实开源仓库）+ 隐藏验收 + `prepare/grade/scorecard` + TRAE/Codex/Cursor/Qoder 驱动器 + `dashboard/` 评测控制台（只读 / 本地启动） |
| `office-eval/` | 办公产物判分（实验）：xlsx 任务 + openpyxl 隐藏验收 + 判分/自测；docx 任务待加 |
| `walkthrough-harness/` | 借鉴 Harness² 的 8 组件骨架（system prompt / guardrails / memory / tool guidance / skills / subagents / scripts / plugins） |

## 不包含什么

- **不含 `runs/` 案例库**：报告、截图、日志、产物都不在本包内。方法可以独立使用；需要样本时按本包流程自己跑一轮。
- `runs/` 默认写在 `.gitignore` 里：证据常含账号、桌面和登录态，是否入库由你决定。
- **不含任何被测产品的账号、登录态、截图或原始日志**。
- 不含 AI 编程工具的**完整**能力评测方法：`code-eval/` 有 15 个任务（12 档 + L4b 对照 + 多模块改造/从零全栈各 1 个，含一个真实开源仓库和一个 Node.js 并发任务）和一套判分骨架，回答的是「这几个任务过不过」，不是「编程能力打几分」；办公侧只有 xlsx 一个任务，还没在真实办公 agent 上跑过。

## 依赖

Linux / macOS / Windows 都能跑；Linux 最完整，macOS 与 Windows 用 `wt.py` 走原生截图 / 点击，隔离靠独立用户或虚拟机。

需要：Python 3.9+、git 2.20+（`new-run.sh` 找仓根、钩子和 `code-eval` 的 diff 都要用）、tesseract（含 `chi_sim`）、Chrome/Chromium，以及四个 pip 包（requests、websocket-client、markdown、Pillow——Pillow 只用于截图涂白）。跑 `harness/webapp_accept.mjs` 或 `code-eval` 的 L12 需要 Node 20+；`office-eval` 另需 `openpyxl`（`pip install -r office-eval/requirements.txt`）；单文件 HTML / PDF 用 Chrome / Chromium / Edge 生成。Linux 跑真实桌面全量走查不需要 Xvfb；`ffmpeg`、`xdotool` 必装，Xvfb + openbox + dbus 只在无头 / CI 时安装使用。

完整安装命令与排错见 [`INSTALL.md`](INSTALL.md)。

## 快速开始

```bash
# 准备：建本轮目录（三平台）
#   生成 shots/ screens/ logs/ trace/ artifacts/，并从 templates/ 复制
#   tool-profile.md、ui-map.md、task-plan.md、task-trace.md、report.md 骨架，
#   外加 logs/task-trace.txt 与 logs/crawl-notes.txt
python3 harness/wt.py new-run 2026-10-19-<tool>

# 0. 先做工具调研（20–30 分钟，只读文档，不预演界面）
#    产出 runs/<date>-<tool>/tool-profile.md（new-run 已复制模板）
#    来源优先级与 8 项清单见 METHOD.md 的 Step 0

# 1. 预检（三平台）
python3 harness/wt.py preflight

# 2. 启动应用（带 --run 才会写事件日志）
#    Linux：默认全新 HOME；需要登录态时设 WALKTHROUGH_HOME / WALKTHROUGH_DBUS
python3 harness/wt.py --run runs/<run> launch --log runs/<run>/logs/app.log -- /usr/bin/<app>
#    macOS：--app 走 `open -a`；Windows：直接传 exe 路径
python3 harness/wt.py --run runs/<run> launch --app "<AppName>" --log runs/<run>/logs/app.log
#    macOS 要给应用传参数时，再加 `-- <参数...>`（例如 -- --new-window）

# 3. 页面地图（45–90 分钟）：把产品点一遍，把界面和控件列全
#    先启动、再枚举——ui-map.py 要连调试端口，应用没起连不上
#    标题必须以 S 编号开头，否则 coverage 会报 has no S-number
python3 harness/ui-map.py --port 9339 --out runs/<run>/ui-map.md --title "S1 首屏"
python3 harness/wt.py coverage runs/<run>     # 未归属控件 + 缺首访图/缺状态矩阵

# 4. 原生 GUI：截图 / OCR 找坐标 / 点击（三平台）
python3 harness/wt.py --run runs/<run> shot runs/<run>/shots/01.png
python3 harness/wt.py --run runs/<run> ocr runs/<run>/shots/01.png
#    OCR 给的是截图内的像素坐标；多屏负原点或 Retina 缩放下用 --shot 换算
#    默认点完自动补一张截图（--no-capture 关掉），audit 会据此配对 click → shot
python3 harness/wt.py --run runs/<run> click 300 241 --shot runs/<run>/shots/01.png

# 5. Electron / WebView：CDP 读 DOM、按文字点、截渲染层
#    启动时加 --remote-debugging-port=9339
python3 harness/cdp.py text
python3 harness/cdp.py clicktext "登录" --capture runs/<run>/shots/02-after-click.png
python3 harness/cdp.py clickel "允许读取" --nth 0   # 选项带序号时按第 n 个匹配点
python3 harness/cdp.py shot runs/<run>/shots/02.png

# 6. 出 PDF（中间 HTML 只写临时目录）
#    截图写在发现下面（正文就地引用），默认不再堆附录；--appendix 才追加未引用的图
#    账号名/收款码用 --redact 涂白（改像素，不是盖白块），也可写进 captions.json 的 redact
python3 harness/wt.py report runs/<date>-<tool> --redact 10,865,300,75
#    shots/captions.json 同时支持图注与指令：
#    {"02-home.png": "首页", "exclude": ["t6-*"], "redact": {"*": [[10,865,300,75]]}}
#    另有 --exclude 't6-*'（按图排除）与 --max-figure-height 90mm（压图高）

# Linux 隔离桌面（可选；macOS / Windows 用独立用户或虚拟机）
./harness/desktop-up.sh :98 1440x900x24
```

> macOS / Windows 分支已经实现，但尚未在真机实测；第一次用先跑 `python3 harness/wt.py preflight`，按输出补依赖和权限。

## LLM 自带走查（可选）

给 harness 配一个 OpenAI-compatible 视觉模型，就可以不让外部 Agent 操作，自己走查 AI 产品：

```bash
export WT_LLM_BASE_URL=https://api.openai.com/v1
export WT_LLM_API_KEY=...
export WT_LLM_MODEL=gpt-4o-mini

python3 harness/wt.py new-run 2026-10-29-<tool>
python3 harness/wt.py --run runs/2026-10-29-<tool> agent \
  --goal "完成一次完整走查：打开对话、发一条消息、记录异常" \
  --backend cdp --port 9339 --max-steps 20
```

- `--backend cdp`：Chromium / Electron 产品，走截图 + DOM 文本 + CDP 输入；先启动被测产品并加 `--remote-debugging-port=9339`
- `--backend desktop --display :0`：Linux/X11 原生桌面，截图 + xdotool；`--ocr` 才加 tesseract 文本
- `--dry-run`：只观察和计划，不点击；`--max-steps` / `--max-total-tokens` 控成本
- 产物：`shots/agent-step-*.png`、`events.jsonl`、`findings.json`、`agent-summary.md`
- key 只从环境变量读取，不接受命令行参数；不要写进仓库或报告。不要把明文 key 留在 shell 历史里，可用 `read -rs WT_LLM_API_KEY && export WT_LLM_API_KEY` 或密钥管理器
- 第一版只承诺 Linux；macOS / Windows 的 CDP 可用，原生输入未实测
- operator 的 `findings.json` 是待复核的发现，不是最终结论；报告仍按 METHOD 写，`audit` 仍要做

模型必须支持图片输入。纯文本模型即使开 `--ocr` 也只能靠坐标猜，不能当作可靠走查。

## 日常工作流（单仓）

公开仓同时是工作区；报告、截图和日志只留在本地：

1. 建本轮目录：`python3 harness/wt.py new-run 2026-10-19-<tool>`
   （生成 `runs/<run>/{trace,shots,logs,artifacts}`，并从 `templates/` 复制 `tool-profile.md`、`task-plan.md`、`task-trace.md`、`report.md`）
2. 跑走查、写 `report.md`，产物放同一目录
   （模板会自动复制到 `<run>/`，`task-trace.md` 落在 `trace/`；手工建目录时要自己 `cp`。`build-report.py` 和 `wt.py audit` 都读 `<run>/report.md`）
3. 只提交方法 / 模板 / harness 的改动；`runs/` 已被 `.gitignore` 忽略
4. 首次 clone 后跑一次 `./harness/install-git-hooks.sh`

钩子会拦：`runs/` 路径、图片 / PDF / 日志 / docx / zip 等证据文件、邮箱、`/home/<user>`、飞书文档链接、`machine_id` 参数，以及 `.git/pii-terms` 里自己加的账号名。

不要 `git add -f runs/`，不要 `git clean -xdf`（会删掉未跟踪的证据）。

**备份**：`runs/` 只在本机，没有远程副本。换机、误删、硬盘故障都会丢；自己定期同步到外置盘或网盘。

## 分享报告（单文件）

Markdown 的相对图片路径只在本机成立；直接把 `.md` 发给别人，对方会看到裂图。用 `report_share.py` 出单文件：

```bash
# 一份 MD 出 HTML + PDF + 钉钉单文件（原图）
python3 harness/report_share.py runs/<run>/report.md --outdir runs/<run>/dist --all

# 只出钉钉单文件：original 原图（约 2.5MB，清晰）/ compact 压缩（约 1MB，字会糊）
python3 harness/report_share.py runs/<run>/report.md --outdir runs/<run>/dist --dingtalk original
```

- PDF 适合微信 / 邮件；单文件 HTML 适合浏览器查看；钉钉导入实测支持 `data:image/png;base64,...`，官方文档只保证 `![](http://...)`。
- 表格里 480px JPEG 缩略图放大必糊；正文用原图，表格要缩略就用 960px 无损 PNG。
- `thumbs/` 引用会自动回退到同名的全尺寸原图；图片不会上传到任何公网图床。

## 事件日志、审计与版本锚定

**事件日志**：带 `--run runs/<run>`（或环境变量 `WALKTHROUGH_RUN`）的命令会往 `runs/<run>/events.jsonl` 追加一行：
`ts / os / action / result / duration_ms / target / screenshot / detail`。
`new-run` 会同时写 `harness.json`，记录本轮实际用的 profile、OS、Python、tesseract、Chrome 版本。
`cdp.py` 也读 `WALKTHROUGH_RUN`，写 `cdp:text` / `cdp:click` / `cdp:shot` 等事件；跑 CDP 前先 `export WALKTHROUGH_RUN=runs/<run>`。

**审计**：

```bash
python3 harness/wt.py audit runs/<run>
```

逐项检查：`report.md` 是否存在、报告里引用的截图（`shots/` 与 `screens/`）是否都在、事件里的截图文件是否还在、有没有 error 事件、每次 `click` 之后是否补了截图（`wt.py click` 默认点在截图，`cdp.py --capture` 同理）、`harness.json` 是否存在、**任务数 8–15（只数填了结果的行）**、**`ui coverage`（界面/控件/状态矩阵/一级入口）**、**每条发现是否带「归因 / 复现」**。`audit` 只对 FAIL 返回非 0，证据为空或只有 WARN 时仍可能退 0；CI 请用 `audit --strict`（WARN 也视为失败）。

**Profiles**：

```bash
python3 harness/wt.py profiles          # 列出 linux-desktop / linux-x11 / macos / windows / ci
python3 harness/wt.py --profile linux-desktop preflight
```

profile 放在 `harness/profiles/*.json`，声明 display、geometry、OCR 语言、隔离方式；`--profile` 不传时按 OS 自动选（Linux 默认 `linux-desktop`，Xvfb 用 `linux-x11`）。

检查项自己有回归测试（标准库 unittest，无需安装）：

```bash
python3 -m unittest discover -s tests -v     # 107 个用例，覆盖 coverage / audit / CLI / 出片涂白与图注
```

一条命令跑完整健康检查（单元测试、15 个任务规格、两套自测、Node 语法、Python 编译）：

```bash
python3 verify_all.py            # 约 1 分钟
python3 verify_all.py --quick    # 跳过两个慢自测
python3 verify_all.py --strict   # SKIP 也算失败，适合发布门禁
```

用例在临时目录里造"假 run"，只改一处再断言工具的反应；改判据时先跑一遍，别让"拦住偷懒"的检查在重构里悄悄失效（`tests/README.md`）。

**真实桌面优先**：全量走查默认在现有 GNOME 会话跑。`linux-desktop` 用 `DISPLAY=:0` + Xwayland auth，保留 GPU、原生文件选择器、通知、桌面宠物和电脑操控。`linux-x11` 与 `ci` 才设 `LIBGL_ALWAYS_SOFTWARE=1` 走软件渲染（由 profile 的 `software_gl` 字段决定），只用于 CI / 无人值守冒烟；真实桌面上不要加 `--disable-gpu`，否则动画和滚动会变慢，观感结论会失真。

**版本锚定**：`harness/harness.lock` 记录 `wt_version`、最低 Python / tesseract 版本和已实测平台；`preflight` 会对照它给出 WARN。报告附录建议带上 `harness.json` 的版本信息。

## 跨平台对照

| 能力 | Linux | macOS | Windows |
|---|---|---|---|
| 截图 | `ffmpeg` x11grab | `screencapture` | PowerShell + .NET |
| 点击 | `xdotool` | `cliclick`，没有则 AppleScript | `ctypes`（user32） |
| OCR | tesseract | tesseract（brew） | tesseract（PATH） |
| Electron / CDP | `cdp.py` | `cdp.py` | `cdp.py` |
| 隔离 | 默认真实桌面；Xvfb 隔离仅 CI/无头 | 独立 macOS 用户或虚拟机 | 独立用户或虚拟机 |
| 出 PDF | Chrome / Chromium | Chrome / Chromium / Edge | Chrome / Chromium / Edge |
| Git 钩子 | bash | bash | Git Bash |

macOS 需要给终端 / agent 进程开 **屏幕录制** 和 **辅助功能**；Windows 需要在交互式桌面会话里跑，服务账号的 session 0 截不到界面。

### 不抢键盘鼠标

- **`wt.py click` 会移动你的物理指针**（Windows `SetCursorPos` + `mouse_event`，macOS `cliclick`，Linux `xdotool`）。这是唯一会抢输入的命令。
- `harness/cdp.py` 的 `clickel` / `clicktext` / `clickxy` / `type` / `key` 走 DevTools 协议，只作用于应用内页面，**不碰系统输入，也不需要窗口在前台**。
- 截图、OCR、`launch`、`report` 都不注入输入。
- 完全不想被碰：`export WALKTHROUGH_NO_NATIVE_INPUT=1`（或给单次调用加 `--no-native-input`），`click` 会直接拒绝并提示改用 `cdp.py`；`preflight` 会打印当前模式。
- 必须点原生弹窗（文件选择器、系统授权）时，把整轮走查放进隔离桌面 / 虚拟机 / 独立用户，那一轮里随便动。

## 适配点

- `python3 harness/wt.py preflight`：三平台统一预检（Python、tesseract、Chrome、截图/点击工具、Linux display）。
- `node harness/webapp_accept.mjs --dir <project> --out accept.json`：全栈 TaskFlow 参考验收（43 项，随机端口 + 全新 DB + 进程树回收）。全过退 0，任一 FAIL 退 1；结果 JSON 照常写出。
- `wt.py shot|click|ocr|launch|new-run|report`：三平台统一入口；命令参数放在 `--` 之后（`launch --log x -- /path/app`）。
- `preflight.sh`、`desktop-up.sh`、`app-launch.sh`、`shot.sh`、`click.sh`、`portal-shot.py` 是 Linux 原生脚本，保留兼容；跨平台优先用 `wt.py`。

## 方法要点

1. **先定评测范围**：覆盖哪些能力域 / 界面 / 任务类型，哪类问题在范围内，哪些不在（及原因）。
2. **任务驱动，不按菜单逛**：8–15 个用户任务（从页面地图派生，每屏至少一条），覆盖首启、核心任务、产物取回、失败态、连续任务、设置。
3. **每条问题四件事**：具体元素 + 导致的后果 + 证据 + 建议；再加**影响面、最小复现、置信度**。不写「用户找不到」。
4. **0–4 严重度**：4 阻断 / 3 严重 / 2 轻微 / 1 观感 / 0 不是问题；S3/S4 必须人工复核，n=1 不写成功率。
5. **报告先给问题总览**（按严重度 × 置信度分布 + 最该先处理的 3 条），另有「已验证正常的行为」，防止团队把没坏的部分一起改。

## 边界（写进交付，不要省）

- 走查 agent 交的是「不疲劳的第一遍」候选问题，最终判定仍需人。
- n=1 是探索性观察，不外推到其他版本 / 环境；不写成功率。
- 单评分者（尤其 AI）严重度不可信；S3/S4 必须人工复核。
- 截图读屏得到的图标含义属于推断，标「推断」或「未核实」。
- 不把「发现的问题多」当质量信号；AI 会多报，也会有误报。
- 不能交：托盘 / 系统通知 / 文件选择器 / 拖拽 / 自启 / 自动更新 / 多显示器；Xvfb 下的性能与启动耗时；移动端；企业后台；真实扣费；服务端行为；动效细节。

## 来源与许可

- 方法参考 NN/g 的严重度与可执行发现、Maze / DHS 的报告结构、Builders Camp 的「前三 + backlog」，出处见 `METHOD.md` 第 13 节。
- `walkthrough-harness/` 只借鉴 Google Harness²（Apache-2.0）的组件划分，未复制其代码，也不跑其 benchmark。
- 本包以 MIT 许可发布，见 [`LICENSE`](LICENSE)。
