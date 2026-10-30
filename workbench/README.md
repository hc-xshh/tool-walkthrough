# 工作台（Workbench）

把 harness 的常用动作收进一个本地页面：**配置模型 → 定维度 → 选产品跑 → 看报告**。

```bash
./start.sh                                  # 停掉旧实例，起新的（默认端口 8790）
./start.sh --reuse                          # 只复用，不重启
./start.sh --force                          # 有任务在跑也强制重启
python3 workbench/server.py                 # 等价的直接启动（Windows 用这条）
```

`start.sh` 按端口探测旧实例（`server.py` 会在响应头里报 `WalkthroughWorkbench`），并用 `runs/workbench/server.json` 记住上次启动的端口，所以不需要知道旧进程开在哪个终端。收旧进程用 SIGTERM，`server.py` 会走 Ctrl-C 同一条路径把子任务停掉，不留孤儿进程。

> 2026-10-30 起，工作台只有 **接入 / 维度 / 场景 / 运行 / 报告 / 日志**；下面提到「驱动器 / 评测页 / 走查页」的段落是命令行遗留路径，界面上已经没有这些入口。

只依赖 Python 标准库。走查后端（CDP / 桌面）需要 `harness/requirements.txt` 里的包：
第一次打开「配置 → 基础环境」，缺什么点「安装依赖」——装到 `workbench/.deps/`，不碰系统 Python，
适合 Debian/Ubuntu 的 PEP 668 环境（没有 venv 也能用）。被测产品要先按 `README.md` 的说明启动好。

## 它做什么

| 页面 | 动作 | 底层命令 |
|---|---|---|
| 配置 | 大模型 API Key（服务商预设 / 模型 / 高级 endpoint）+ 网络搜索 provider/key + 基础环境自检；安装依赖 | — |
| 接入 | 可测应用目录；应用启动 / 重启 / 路径；高级里保留手工补充（过渡） | — |
| 维度 | 维度增删改（名称 / 指标 / 单位 / 采集方式 / 聚合）+ 该维度下的场景导航 | — |
| 场景 | 场景增删改；按维度筛选；看每个场景的采集状态与记录 | `workbench/survey_run.py`（命令采集） |
| 运行 | 选一个场景 + 勾多个产品 → 顺序自动跑，一个产品一份 run | `workbench/survey_batch.py` |
| 报告 | 维度 × 产品矩阵、逐格明细、导出 Markdown | — |
| 日志 | 结果概览、实时日志、截图、文件、停止 | — |

驱动器清单（显示名、GUI 端口、CLI 命令、可透传参数）来自 `code-eval/drivers.json`；用户在接入页注册的驱动器存在 `plugins.json`，加载时合并。工作台不再维护第二份清单，页面上的端口提示和 Qoder 专属开关也由记录的 `kind` / `features` 决定。

## 界面约定

页面是原生 HTML/CSS/JS，没有构建步骤。左侧导航是 **接入 / 维度 / 场景 / 运行 / 报告 / 日志**，**配置固定在最下面**；配置管模型和基础环境，接入管应用与驱动器，维度管定义，场景管「怎么点亮维度」，运行管采集，报告管对比，日志收结果和证据。几个和「少做错」有关的约定：

- **表单不丢**：运行页选的产品 / 版本 / 维度存在 `sessionStorage`，切换页面、点刷新都还在；配置页点顶部「刷新」时会保留未保存的输入（浏览器硬刷新仍会丢）。
- **先校验再提交**：Base URL / 模型 / 端口 / 步数 / run id 在页面上先校验；不满足时按钮置灰并在旁边写原因，不会先起进程再失败。
- **Qoder 一次一个任务**：选中 Qoder 且勾了多个任务时，开始按钮直接禁用并说明原因；其他驱动器不受这条限制。
- **自检先给结论**：配置页的基础环境先显示 `通过数 / 总数`，失败项排前面；`只看需处理` 折叠通过项。应用端口、驱动可用性在接入页，不混进基础环境。
- **日志页先看结果**：完成的 run 默认打开「概览」，从 `summary.json` / `findings.json` 读判定和候选发现；日志和产物各占一个 tab。
- **产物分组**：结果文件、截图、工作区文件分开；`.git/` 和 `work/` 默认收起，避免 40 个文件里先看到 36 个 git 内部文件。
- **日志可跟随**：默认滚到最新；往上翻会暂停跟随并出现「跳到最新」，刷新时保留滚动位置。
- **证据可预览**：截图点开是整张图的灯箱；`.md` / `.json` / `.log` 在页面内只读预览，不把原始 JSON 甩到浏览器标签页里。
- **先算场景再跑**：勾完维度先点「算一下要跑哪些场景」，页面列出最小场景集和没被覆盖的维度；不会闷头启动。
- **一次运行一份 JSON**：`runs/survey/<run_id>/run.json`，里面是 measurements + 当时的定义快照；报告只读这些文件，不读数据库。
- **窄屏可用**：≤860px 侧栏变顶栏，≤640px 日志列表改为卡片式行；360px 宽没有横向滚动。
- **key 设置够用就好**：服务商预设自动带 endpoint / 模型；API Key 只写不读，支持显示刚输入的草稿；「保存并测试」会先保存当前表单再发 ping；高级设置里才放 Base URL 和超时。
- **键盘**：配置页回车保存；原生 `<dialog>` 支持 Esc 关闭。

改完前端先跑 `python3 verify_all.py --quick`（含 `app.js` 语法），再在 1440px 和 390px 宽度各点一遍六个页面和运行详情。

产物仍然落在 `runs/<run>/`，工作台不发明新的目录结构。跑完可以直接用命令行接手：

```bash
python3 harness/wt.py audit runs/<run>
python3 harness/wt.py report runs/<run>
```

## 配置存在哪

`~/.config/tool-walkthrough/config.json`，权限 `0600`（目录 `0700`），不进仓库：

```json
{
  "llm": {
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o-mini",
    "api_key": "sk-...",
    "timeout": 120
  }
}
```

- 换机器 / 给别人：直接复制这个文件；**不要**提交进 git。
- 用 `WT_CONFIG=/path/to/config.json` 可以换一份配置（测试或隔离用）。
- 页面上 key 是只写的：保存后只显示 `****abcd`；「保存并测试」会先保存，再发一条 8 token 的 ping。

自定义接入单独存 `~/.config/tool-walkthrough/plugins.json`（`0600`），不写进仓库。它保存用户添加的应用 / 驱动器、内置应用的可执行文件路径，以及一句话接入生成的 `discovered` 产品记录；内置清单仍在 `workbench/apps.py` 和 `code-eval/drivers.json`。

## DeepSeek key 与 401

DeepSeek 搜索和模型共用同一个平台 API Key；如果 key 本身无效，会先在搜索请求上看到：

```text
HTTP 401: Authentication Fails, Your api key: ****xxxx is invalid
```

这不是“DeepSeek 不支持搜索”，而是认证失败。先用配置页的「大模型 API Key → 保存并测试」验证；模型 ping 也 401 时，搜索一定 401。

- 官方 API Key 通常在 `https://platform.deepseek.com/api_keys` 创建，以 `sk-` 开头；
- 网页登录 token、云厂商的 AccessKey/SecretKey 不是同一种认证，不能直接填在这里；
- 如果 base URL 不是 `https://api.deepseek.com`，key 必须是对应网关的 API key；
- 搜索 key 留空时 DeepSeek 复用模型 key；填了单独的搜索 key 时以搜索 key 为准。

## 一句话加产品

接入页顶部是「一句话加产品」，例如：

```text
加上 Kimi Work
```

它启动一个 `discover` job，按顺序做：

1. 查固定 `catalog/*.json`；命中就只提示已在谱系，不重复添加；
2. 未收录时用配置的搜索 provider（DeepSeek 可复用模型 key）；
3. 用 LLM 从搜索结果整理厂商、定位、产品形态、官网/文档；
4. 在本机找安装：Linux 扫 `.desktop` + PATH，macOS 扫 `/Applications`，**不自动下载/安装/启动**；
5. 找到 GUI 可执行文件时自动加一条 custom app 连接（分配空闲调试端口）；
6. 写入 `plugins.json` 的 `discovered`，产品卡显示来源、本机状态和下一步动作。

找到应用并启动后，产品卡直接跳到「运行」页开始采集；驱动器仍显示「待驱动器」，等通用/专用 driver。未安装时给官网入口和「安装后重新查找」，不假装能测。

> 这一步会调用一次 DeepSeek Search API（`/v1/tools/search`），再用模型整理信息；两者都会消耗额度。

## 产品谱系

`catalog/*.json` 是项目里的只读产品谱系：一个文件一个家族，包含公司、定位、产品线、可测面和来源。前端「产品谱系」卡片直接展示，不需要改代码；新增 WorkBuddy / Kimi / ZCode 这类家族就是加一个 JSON 文件。用户不编辑家族/产品，接入页只负责展示和连接。

产品谱系里的 `app_id` / `driver_id` 只引用内置 app 和 driver；可执行文件路径、端口、key 仍然属于本机连接，不写进 catalog。

## 应用接入

接入页先展示固定产品谱系，再用「连接与驱动」表回答「现在本机哪些能测」。手工「添加应用 / 注册驱动器」已收进页面底部的「高级 / 手工补充」折叠区，是过渡入口，正式版会移除：

- **应用**是被操作的软件（Qoder / Cursor / TRAE / 自定义 GUI）；
- **驱动器**是让软件自动完成评测任务的适配器；
- **走查**只需要应用带 CDP 调试端口；
- **评测**还需要已注册驱动器。

表里的「可连接 / 有驱动器」是支持能力，「状态」是当前是否就绪；未安装的 Cursor / TRAE 可以直接点「设置路径」，不用改环境变量。

扩展分两种：

1. **添加应用**：名称 + 可执行文件 + 调试端口。适合任何 Chromium / Electron 应用；添加后走查 CDP 可用，评测列会显示「需驱动器」。
2. **注册驱动器**：填写 `drive_*.py` 路径、GUI 端口或 CLI 命令、可选特性。脚本需要实现 `run_tool.py` 的 driver 协议（`--task/--workdir/--rep/--out/...`），注册后会进入评测页的驱动器列表。

自定义驱动器是高级操作：工作台只校验脚本存在，不校验行为；只注册你信任的本地脚本。

「一句话加产品」已经接上：输入「加上 Kimi Work」→ 先查固定产品谱系，未收录再联网搜索 → LLM 整理厂商/定位/形态 → 本机安装探测 → 产品卡。找到 GUI 连接后可从卡片启动应用、跳到运行页采集；自动判分要等通用/专用 driver。见根目录 `TODO.md`。

## 基础环境自检

配置页只检查走查 / 评测必需的基础环境；被测应用端口、驱动可用性在接入页，key 在配置表单里：

| 检查 | 失败时怎么办 |
|---|---|
| CDP 依赖（websocket-client / requests） | 点「安装依赖」（装进 `workbench/.deps`，并带上 openpyxl） |
| 真实桌面会话 | v6.14 起只认真实桌面：活跃 logind session + 真实 X11/Wayland 输出；Xvfb 会被拒绝 |
| xdotool | `sudo apt install xdotool`；只影响桌面后端、原生点击和真实窗口校验 |

接入页会显示 Qoder / Cursor / TRAE 的启动状态、调试端口和驱动可用性；key 在配置页表单里，不再重复放进自检。

评测页启动任何驱动前都会再查一遍：GUI 驱动看调试端口和依赖，CLI 驱动看可执行文件是否在 PATH 里；
不满足直接拒绝，不会建 run 目录，也不会让你等 10 秒才看到报错。驱动器下拉框里不可用的会标灰并自选一个可用的。

## 启动被测应用

「接入 → 可测应用」能直接带 `--remote-debugging-port` 启动 Qoder / Cursor / TRAE；同一张表也显示驱动器的可用性和特性：

- 没在运行 → 按钮是「启动」；
- 在运行但没带端口 → 按钮是「重启并开端口」，会先确认，再 SIGTERM 主进程；
- 已经在带端口运行 → 显示「已就绪」；`/api/apps/<id>/launch {"restart":true}` 仍会真的重启（SIGTERM + 重新拉起），打开任务目录时如果关掉最后一个窗口导致应用退出，也走这条路；
- 如果应用弹出保存对话框没退出，工作台会报「没有退出」而不是强杀；
- 端口起来后，接入页的应用状态和驱动器会变绿。

可执行文件路径可以用环境变量改：`WT_QODER_EXE` / `WT_CURSOR_EXE` / `WT_TRAE_EXE`。

## 弹窗怎么处理

GUI 的弹窗会随版本变（信任、登录、额度、协议、更新）。规则在
`code-eval/tools/dialogs.py`，是数据不是代码，分三档：

| 档位 | 例子 | 行为 |
|---|---|---|
| safe | 信任此作者、稍后提醒、以后再说 | 自动点，记 `dialog_handled` |
| blocked | 登录 / 验证码 / 额度 / 协议 / 未保存 / 更新重启 | **不点**，截图 + `dialog_blocked`，本轮失败并写清原因 |
| unknown | 没见过的模态框 | **不猜**，截图 + `dialog_unknown`，本轮失败 |

- 检查时机：启动后、每次输入前、以及等待过程中**空闲时**轮询；生成中不打断。
- 证据：`results/*.trace.jsonl` 的 `dialog_*` 事件，加 `<trace>.dialog.png` 截图。
- 工作台运行详情会显示「弹窗 自动 N · 需人工 M」，悬停看具体文案。
- 加规则：`SAFE` 加 `(页面字样, (要点的按钮,))`；`BLOCKED` 加 `(页面字样, 原因)`。
  不要把「对话框里的任意按钮」加进 safe。

## 真实桌面要求（v6.14 起）

上游在 v6.14 移除了虚拟桌面路径，工作台跟着执行：

- 走查 / CDP 后端要求 logind 里有活跃、带 seat 的会话，且 `DISPLAY` 与这个会话自己的 Display 一致；
  容器/VM 里它可能是 `:1` 而不是 `:0`（本项目按会话判定，不硬编码 `:0`）。Xvfb、无 seat 的会话仍会被拒绝。
- CDP 还会校验目标背后有可见的真实窗口（`xdotool` 查窗口标题 / class）。
- 基础环境自检第一项就是这条；不满足时「开始评测」和「开始走查」都会直接拒绝，不会跑到一半才失败。

## Qoder 在 Linux 上跑评测

`drive_qoder.py` 建工作区用的是 Windows 的文件夹选择器，Linux 上可以绕开：

1. 接入页把 Qoder 带端口启动（「重启并开端口」）——**先重启，再打开目录**，
   顺序反了会报「还没带调试端口启动」；
2. 评测页选**一个**任务，直接点「开始评测」——工作台自己建好
   `runs/<run_id>/work/<task>-r1`、在 Qoder 里打开（校验窗口标题里真的出现了目录名），
   再传 `--skip-workspace` 启动驱动。`--skip-workspace` 在选 Qoder 时默认勾上。

   想提前看一眼界面的话，「重新在 Qoder 打开任务目录」按钮仍然在（可选）。

   打开目录时会先关掉标题同名（同一个任务目录名）的旧窗口：Qoder 启动会把上次的窗口恢复回来，
   两个同名窗口会让驱动连错一个。如果关掉的是最后一个窗口、应用跟着退出，工作台会用带调试端口的
   方式重新拉起再打开目录；窗口有未保存改动关不掉时，会明确报错让你手动关。

   打开目录时工作台会在 `runs/<run_id>/` 放一个 `.workspace.json` 标记，下一次「开始评测」会复用它，
   不会报“目录已存在”。只有两种情况会拦：这个 id 已经跑过（有 job 记录），或下面已经有结果——
   这时换一个 run id 即可。

Qoder 1.37 的界面和旧驱动假设不一样，驱动已适配：

- 入口叫「新会话」（旧版是「新的任务」），驱动两种都认；
- 打开新目录会弹「是否信任此作者」，驱动会自动点「是，我信任此作者」；
- 发送优先用 Enter，不行再点 `Send message`。

Linux 上 Qoder 没勾「工作区已手动建好」时，工作台直接拒绝，不会跑到一半才报 popover 超时。

驱动用 `cdp.py --match-title <任务目录名>` 选窗口，Qoder 同时开着多个窗口也不会连错——
窗口标题里带目录名（`L1-split-bill-r1 - Qoder CN IDE`）。

只想「看着 Qoder 编码」的话不用走评测，直接用走查页的 CDP 后端，不需要建工作区。

## 安全边界

这是一个**本地单用户**工具，不是服务：

- 只绑 `127.0.0.1` / `localhost`；传别的地址会直接退出。
- 每个写请求要带启动时生成的 token（写在页面的 `<meta>` 里），并校验 `Host` 与 `Origin`，挡 DNS rebinding 和跨站提交。
- key 只经**子进程环境变量**传给 `wt.py agent`，不进 `argv`、不进 `control.json`、不进日志。
- `/api/jobs/file` 只允许读 `runs/` 下的文件，`..` 会被解析后拒绝。
- 一句话接入只做**发现和连接**，不自动下载、不自动安装、不自动登录；找到 GUI 可执行文件后，启动仍需用户点按钮。
- 自定义应用和驱动器都是**本地信任**操作：工作台会按你填的路径启动可执行文件、按你填的脚本路径跑 Python；只添加你信任的东西。
- 网络搜索是可选配置：provider 可选 DeepSeek / Exa / Tavily / Brave / Perplexity；搜索 key 只写不读，模型是 DeepSeek 时复用模型 key，其他 provider 需要单独 key。没有 key 时不联网搜索，也没有内置爬虫兜底。
- 自定义接入存在 `~/.config/tool-walkthrough/plugins.json`（`0600`），不进仓库；写接口同样要 token。
- 产品谱系在仓库 `catalog/*.json`，只读；新增家族是维护者加文件，不是用户操作。
- 没有登录、没有多用户隔离、没有任务队列：同一时间建议只跑一个 run。

## HTTP 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/state` | 配置（脱敏）+ 任务 + 驱动器 + 产品谱系 + 自动发现 + 最近 job |
| GET | `/api/config` | 配置（脱敏） |
| POST | `/api/config` | 合并保存；`api_key` 为空表示保留旧值 |
| POST | `/api/config/test` | 发一条 8 token 的 ping |
| POST | `/api/jobs` | `{"kind":"walkthrough",...}` 或 `{"kind":"eval",...}` |
| GET | `/api/jobs` | 最近 50 条 |
| GET | `/api/jobs/<id>` | 详情 + 产物清单 |
| GET | `/api/jobs/<id>/log?lines=200` | 日志尾部 |
| POST | `/api/jobs/<id>/stop` | 杀整个进程组 |
| GET | `/api/jobs/file?path=runs/...` | 读产物 |
| GET | `/api/doctor` | 环境自检结果 + 被测应用状态 |
| POST | `/api/apps/<id>/launch` | `{"restart":true}` 带调试端口启动/重启 |
| POST | `/api/apps/workspace-open` | 建任务目录并在 Qoder 中打开 |
| POST | `/api/deps/install` | 把 `harness/requirements.txt` 装进 `workbench/.deps` |
| POST | `/api/plugins/apps` | 添加自定义 GUI 应用，或给内置应用设置可执行文件路径 |
| POST | `/api/plugins/apps/remove` | 移除自定义应用 / 恢复内置默认路径 |
| POST | `/api/plugins/drivers` | 注册本地 `drive_*.py` 驱动器 |
| POST | `/api/plugins/drivers/remove` | 移除自定义驱动器 |
| POST | `/api/config/test-search` | 用已保存的搜索 provider/key 搜一次，返回结果和来源 |
| POST | `/api/jobs` | `{"kind":"discover","query":"加上 Kimi Work"}` 启动一句话接入 job |
| POST | `/api/discovered/remove` | 移除一条自动发现产品记录（不删除本机程序/已有连接） |

## 已知限制

- GUI 驱动器（Qoder / Cursor / TRAE）要求被测应用带 `--remote-debugging-port=<端口>` 启动，
  且运行 workbench 的解释器要装 `websocket-client`；启动前会预检，不满足直接拒绝，不会等你 10 秒才报错。
- `drive_qoder.py` 创建 Qoder 工作区时用 Windows 的文件夹选择器（`harness/pick-folder.ps1`）。
  Linux 上要么手动建好工作区再跑 `drive_qoder.py --skip-workspace`，要么用走查页的 CDP 后端
  （`wt.py agent` 不需要工作区，适合「看着它编码」这种走查）。


- 评测页的驱动器（Codex / TRAE / Cursor / Qoder）**不读**这个 key，它们用各自的登录态；工作台的 key 目前只服务走查 operator。
- `workbench/.deps` 是可选依赖目录（约 30MB），已在 `.gitignore` 里；删掉后重新点「安装依赖」即可。
- 日志接口只返回最后 500 行；更早的内容看 `runs/workbench/jobs/<id>.log`。日志仍是 2 秒轮询，已保留滚动位置和「跟随最新」，但不是流式推送。
- 结果概览依赖 `summary.json` / `findings.json`；文件还没生成或格式不认识时只显示提示，不猜判定。
- 自定义驱动器只校验脚本存在，协议正确性和行为需要使用者自己保证；注册后会立即出现在评测页驱动器列表。
- 一句话接入的本地探测目前是 Linux `.desktop`/PATH + macOS `/Applications`；Windows 和其他安装形态还要补。自动发现的产品来源是搜索摘要 + LLM 整理，未核实，需要用户看来源。
- 自动发现产品卡现在只能开始走查；评测要等通用/专用 driver。
- 自定义应用只支持 GUI + CDP；CLI 工具按驱动器注册。
- 没有断点续跑、没有队列、没有并发控制。
- 页面只在 Chromium 手动验收；360px 以上做了响应式检查，Safari / Firefox 未测。
- 「在 Qoder 中打开任务目录」依赖 Qoder 把命令行打开的文件夹当成工作区；如果它不认，驱动仍会回退到原生对话框（Linux 上会明确报错）。这一步需要在真机上验一次。

## 下一步（还没做）

1. 用配置的 key 跑编码任务：新增 `code-eval/tools/drive_llm.py` + 一个 JSON 动作协议的编码 agent 循环（`read_file` / `write_file` / `run_tests` / `done`），判分仍交给 `grade.py`。
2. 走查页把 `ui-map` / `coverage` / `report` / `audit` 串成向导。
3. 日志页补 token 用量和按任务的耗时汇总（日志已做尾部 500 行 + 跟随最新）
4. 给自定义驱动器补一个模板 / 协议校验，降低「注册成功但跑不起来」的概率
