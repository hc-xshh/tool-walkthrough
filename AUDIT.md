# 项目体检：可用、可靠、可解释

_体检日期：2026-10-29。只写这次实际跑过的结果；没跑过的在「未验证」里单列。_

## 结论

**可以用，但边界要写清。** 三条主线的入口都能跑通，健康检查一条命令通过；
还没有做到的是跨平台真机、真实办公 agent 和「通过率饱和」后的区分度。

- **可用**：`wt.py` 的 13 个子命令、`code-eval` 的 15 个任务、`office-eval` 的 1 个任务都有可执行入口；
  之前 `preflight` 在 agent shell 里会误报 `display :0` 失败，已修。
- **可靠**：126 条单元测试、51 条 code-eval 自测、5 条 office 自测、15 个任务规格检查全过；
  `verify_all.py` 一条命令可复跑；GitHub Actions 上的 `verify` 已实跑通过（1m12s）。
- **可解释**：判分结果有 verdict / score / requirements / deliverable / claims / quality / usage；
  记分卡带 token 成本；报告有固定六节和边界。文档里的任务数、测试数已和实际对齐。
- **可选任务**：15 个任务都有 `category` / `complexity` / `tags`；`run_tool.py --list` 可看清单，
  `--tasks` 跑一个、`--category/--tag/--complexity` 跑一类、`--pick 1` 取最高难度一个；不写选择器不会跑全量。

## 这次实际跑过的

| 检查 | 结果 | 证据 |
|---|---|---|
| `wt.py preflight` | PASS | Python / git / tesseract / Chrome / CDP / ffmpeg / xdotool / display :0 全 PASS |
| 单元测试 | 126 passed | `python3 -m unittest discover -s tests -q` |
| code-eval 任务规格 | 0 warnings / 15 tasks | `check_tasks.py --strict` |
| code-eval 判分自测 | 51/51 | `code-eval/tools/selftest.py` |
| office-eval 判分自测 | 5/5 | `office-eval/tools/selftest.py` |
| 全量健康检查 | 7 PASS / 0 FAIL / 0 SKIP | `python3 verify_all.py --strict` |
| `report_share.py` | HTML / PDF / 钉钉 MD 三件生成 | 测试报告 + 1 张图，PDF 31KB |
| `webapp_accept.mjs` 失败退出码 | 1 | 空项目跑出 4/20，进程退出 1 |
| Node 语法 | 通过 | `node --check harness/webapp_accept.mjs` + `node --check code-eval/dashboard/app.js` |
| 可视化控制台 | 构建/控制模式通过 | `build_dashboard.py` + `serve_dashboard.py`：15 tasks / 2 runs / 13 results；API 健康、白名单校验、假 driver 启动生命周期；浏览器巡检总览、任务、结果、对比、新建运行 |
| GitHub Actions | success | run 40818710168，1m51s |
| Codex L10–L12 | 9/9 pass | 见 `code-eval/reports/2026-10-29-codex-l10-l12.md` |
| LLM operator 单测 | 17 passed | `test_llm_client` 6 + `test_llm_operator` 12 |
| LLM operator 本地联调 | done / 4 steps / 1 finding | 本地假 AI 页面 + fake OpenAI 服务，CDP 真实截图、输入、点击；产物在临时目录，未入库 |

## 发现与处理

| 级别 | 问题 | 证据 | 处理 |
|---|---|---|---|
| P1 | `preflight` 在 agent shell 里误报 `display :0` 失败，提示还让人启动 Xvfb | 无 `XAUTHORITY` 时 `xdpyinfo` 连不上；实际桌面在跑 | 自动尝试 `/run/user/<uid>/.mutter-Xwaylandauth.*`，并在 PASS 行给出要 export 的完整命令 |
| P1 | `webapp_accept.mjs` 无论多少 FAIL 都退出 0 | 假项目 4/20 仍 `exit 0` | 全过才 0，否则 1；JSON 照常写 |
| P1 | 验收结束按 `accept-*.db` 通配删库，会误删并行任务 | 代码审查 | 只删本轮 `DB_FILE` + `-wal`/`-shm` |
| P1 | 文档写 12 个任务 / 97 条测试，实际 13 个 / 107 条 | `check_tasks`、`unittest` | README 改为 13 个（12 档 + L4b）和 107 条 |
| P1 | 驱动器默认工具名写死旧版本（TRAE 3.4.4、Cursor 3.24.18 等），结果会带错误版本 | 代码审查 | 改通用名；Codex 自动读 `codex --version` |
| P1 | `office-eval` 需要 openpyxl，但没有依赖文件 | README 只说“要装” | 新增 `office-eval/requirements.txt`，README 写入安装命令 |
| P2 | `report_share.py` 的 `<title>` 不转义 | 代码审查 | `html.escape`，新增测试 |
| P2 | `thumbs/a.png` 回退可能取到别的同名图 | 代码审查 | 先取同级 `shots/a.png`，再全目录回退 |
| P2 | 记分卡同任务同 rep 重复文件会算两次 | 曾出现 L12 4 条明细 | 按 `(task, rep)` 取最新文件 |
| P2 | 没有一条命令能回答“这仓现在健康吗” | 每次靠记忆跑多个套件 | 新增 `verify_all.py`（`--quick` / `--strict` / `--json`） |
| P2 | 没有 CI | 仓库根无 `.github` | 新增 `.github/workflows/verify.yml`；GitHub runner 实跑 success（1m12s） |

## 还没解决 / 没验证

- **macOS / Windows 未真机实测**：`wt.py` 分支和 `harness.lock` 都写明“implemented, not tested”；这次只在 Linux 跑。
- **`webapp_accept` 的 43/43 不能在这里复现**：仓库没有 TaskFlow fixture；这次只验证了失败退出码，没有重跑 43 项。
- **office-eval 没有真实办公 agent 数据**：只有参考产物与 3 个错误变体。
- **code-eval 通过率饱和**：Codex 在 L10–L12 9/9 一次过；TRAE 抽测也过。任务能测“会不会”，还测不出“谁更强”。
- **没有覆盖率统计**：`pytest-cov` 未接入；126 条测试覆盖的是工具行为，不是全部分支。
- **`runs/` 只在本机**：约 102MB，未备份；换机/误删会丢证据。
- **`webapp_accept` 仍绑定 TaskFlow 的 43 项检查**：换项目要复制并改检查，不是通用验收器。
- **LLM operator 只用假模型/假页面联调过**：真实 OpenAI-compatible 账号、真实 AI 产品、真实登录态还没跑；桌面后端只在 Linux 代码路径上验证了分派，没有真机点击。

## 边界

这份体检是 **Linux 单机、当前 commit、当前账号配置** 下的结果，不外推到其他系统、其他版本或其他模型。
`n=1` 的抽测只作线索；报告里的 9/9 是 Codex CLI 0.163.0 + DeepSeek 自定义端点，不是 OpenAI GPT。
