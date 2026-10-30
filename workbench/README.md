# 工作台（Workbench）

把 harness 的常用动作收进一个本地页面：**配置模型 → 选任务 → 跑 → 看产物**。

```bash
python3 workbench/server.py                 # http://127.0.0.1:8790/
python3 workbench/server.py --port 8791     # 端口被占用时
```

只依赖 Python 标准库。走查后端（CDP / 桌面）需要 `harness/requirements.txt` 里的包：
第一次打开「设置 → 环境自检」，缺什么点「安装依赖」——装到 `workbench/.deps/`，不碰系统 Python，
适合 Debian/Ubuntu 的 PEP 668 环境（没有 venv 也能用）。被测产品要先按 `README.md` 的说明启动好。

## 它做什么

| 页面 | 动作 | 底层命令 |
|---|---|---|
| 设置 | 存 endpoint / 模型 / key / 超时，测连通；环境自检；带端口启动被测应用 | — |
| 走查 | 填目标、后端、端口、步数，启动 operator | `harness/wt.py --run runs/<id> agent ...` |
| 评测 | 选驱动器 + 任务 + 重复次数 | `code-eval/tools/run_tool.py ...` |
| 运行 | 实时日志、截图、文件、停止 | — |

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
- 页面上 key 是只写的：保存后只显示 `****abcd`。

## 环境自检

设置页底部逐项检查，红了就说明跑之前会失败：

| 检查 | 失败时怎么办 |
|---|---|
| CDP 依赖（websocket-client / requests） | 点「安装依赖」（装进 `workbench/.deps`，并带上 openpyxl） |
| Qoder / Cursor / TRAE 调试端口 | 用 `--remote-debugging-port=<端口>` 重启对应应用 |
| 真实桌面会话 | v6.14 起只认真实桌面：`DISPLAY=:0` + 活跃 logind session + 真实 X11/Wayland 输出；Xvfb 会被拒绝 |
| xdotool | `sudo apt install xdotool`；只影响桌面后端、原生点击和真实窗口校验 |
| LLM key | 到设置页填 endpoint 和 key；只影响走查页 |

评测页启动任何驱动前都会再查一遍：GUI 驱动看调试端口和依赖，CLI 驱动看可执行文件是否在 PATH 里；
不满足直接拒绝，不会建 run 目录，也不会让你等 10 秒才看到报错。驱动器下拉框里不可用的会标灰并自选一个可用的。

## 启动被测应用

「设置 → 被测应用」能直接带 `--remote-debugging-port` 启动 Qoder / Cursor / TRAE：

- 没在运行 → 按钮是「启动」；
- 在运行但没带端口 → 按钮是「重启并开端口」，会先确认，再 SIGTERM 主进程；
- 如果应用弹出保存对话框没退出，工作台会报「没有退出」而不是强杀；
- 端口起来后，环境自检里的对应行会变绿。

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
- 环境自检第一项就是这条；不满足时「开始评测」和「开始走查」都会直接拒绝，不会跑到一半才失败。

## Qoder 在 Linux 上跑评测

`drive_qoder.py` 建工作区用的是 Windows 的文件夹选择器，Linux 上可以绕开：

1. 设置页把 Qoder 带端口启动（「重启并开端口」）——**先重启，再打开目录**，
   顺序反了会报「还没带调试端口启动」；
2. 评测页选**一个**任务，直接点「开始评测」——工作台自己建好
   `runs/<run_id>/work/<task>-r1`、在 Qoder 里打开（校验窗口标题里真的出现了目录名），
   再传 `--skip-workspace` 启动驱动。`--skip-workspace` 在选 Qoder 时默认勾上。

   想提前看一眼界面的话，「重新在 Qoder 打开任务目录」按钮仍然在（可选）。

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
- 没有登录、没有多用户隔离、没有任务队列：同一时间建议只跑一个 run。

## HTTP 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/state` | 配置（脱敏）+ 任务 + 驱动器 + 最近 job |
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

## 已知限制

- GUI 驱动器（Qoder / Cursor / TRAE）要求被测应用带 `--remote-debugging-port=<端口>` 启动，
  且运行 workbench 的解释器要装 `websocket-client`；启动前会预检，不满足直接拒绝，不会等你 10 秒才报错。
- `drive_qoder.py` 创建 Qoder 工作区时用 Windows 的文件夹选择器（`harness/pick-folder.ps1`）。
  Linux 上要么手动建好工作区再跑 `drive_qoder.py --skip-workspace`，要么用走查页的 CDP 后端
  （`wt.py agent` 不需要工作区，适合「看着它编码」这种走查）。


- 评测页的驱动器（Codex / TRAE / Cursor / Qoder）**不读**这个 key，它们用各自的登录态；工作台的 key 目前只服务走查 operator。
- `workbench/.deps` 是可选依赖目录（约 30MB），已在 `.gitignore` 里；删掉后重新点「安装依赖」即可。
- 日志每 2 秒轮询整段重绘，长日志滚动位置会跳；P2 改成增量追加。
- 没有断点续跑、没有队列、没有并发控制。
- 页面只做过 Chromium 手动验收；Safari / Firefox 未测。
- 「在 Qoder 中打开任务目录」依赖 Qoder 把命令行打开的文件夹当成工作区；如果它不认，驱动仍会回退到原生对话框（Linux 上会明确报错）。这一步需要在真机上验一次。

## 下一步（还没做）

1. 用配置的 key 跑编码任务：新增 `code-eval/tools/drive_llm.py` + 一个 JSON 动作协议的编码 agent 循环（`read_file` / `write_file` / `run_tests` / `done`），判分仍交给 `grade.py`。
2. 走查页把 `ui-map` / `coverage` / `report` / `audit` 串成向导。
3. 运行页做增量日志和 token / 耗时汇总。
