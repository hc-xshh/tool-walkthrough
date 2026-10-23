# Changelog

版本号与 `METHOD.md` 顶部的「方法版本」一致。方法、模板或 harness 有实质改动时升一版；只改案例记录不升版。

## v5.2 — 2026-10-22（不改流程：git 变成显式依赖）

- **`preflight` 检查 git**：读 `harness.lock` 的 `git_min`（默认 2.20），capabilities 行输出 `git` / `git:unavailable`；`harness/preflight.sh` 的 host dependencies 也算 git。
- **`find_git()` 先找安装位置、再看 PATH**：Windows 装完 Git 后，长驻的父进程环境还是旧的，只查 PATH 会误报 missing；常见路径（`C:\Program Files\Git\cmd`、Homebrew、`/usr/local/bin`）都会被找到，也可以用 `WALKTHROUGH_GIT` 指定。`git` 仍是 WARN 级——没有它，界面走查照跑，`new-run.sh`、钩子和后面的改动判分才需要。
- **新增 `code-eval/`（实验）**：三个难度档的任务（单文件修 bug / 多文件加功能 / 跨模块排错）、每个任务一份不进 agent 上下文的隐藏验收、`prepare → 改动 → grade` 判分链路（用 git baseline + `git diff` 取改动，快照兜底）、TRAE Agent 的 CDP 驱动器、批量跑与记分卡。`tools/selftest.py` 用假 agent 验证口径：正确解通过、只讨好可见用例的不通过、改 `tests/**` 判 `scope_violation`。

## v5 — 2026-10-22

- **新增 Step 1「产品遍历与页面地图」**（流程从 6 步变 7 步）：不是截一张首屏，而是把产品**点开一遍**——菜单、页签、二级页、弹窗里的按钮，点开才存在。每进一屏截首访图、枚举控件、记导航边；遍历阶段只记不做判断。
- 任务数从 5–8 提到 **8–15**，每个界面至少一条任务；任务标注覆盖的控件 ID。
- `harness/ui-map.py`：CDP 自动枚举按钮/页签/菜单/输入框/图标按钮（含无 role 的 `cursor:pointer` 行），按顶部栏/左侧栏/主区/弹窗分区；多屏追加时 **ID 续号**；`--scope` 把枚举限定在某个弹层内；`--nav-from/--nav-via/--nav-to` 顺手记一条导航边。
- `wt.py coverage [--strict]`：解析 `ui-map.md`，按界面统计控件与归属，列出既无任务也无原因的控件，交叉检查任务 ID 是否存在；`audit` 的 `ui coverage` 同时报界面数与控件数。
- 修复 `cdp.py clicktext/clickel` 的包含匹配：改为**最短标签优先**，否则点「文件」会被「选择文件夹（可选）」抢走。
- `new-run` 多复制一份 `templates/ui-map.md`（含导航表与注释示例）、建 `screens/` 与 `logs/crawl-notes.txt`；`templates/task-plan.md` 增加「覆盖控件」列与「未覆盖控件」表。
- **遍历防偷懒检查**：`coverage` 现在不只数控件，还查「每屏有首访图（`screens/<S 编号>-*.png`）、每屏有任务、界面带 S 编号、导航表行数 ≥ 界面数 − 1、导航目标必须存在」，以及**一级入口覆盖**——左侧栏每个入口和顶部每个菜单，要么在导航表里有一条边，要么备注写「不产生新屏 / 不测」；`audit` 新增 `task count`（只数填了结果的行，8–15）。`--strict` 下这些都给非 0。

## v5.1 — 2026-10-22（不改流程，只加固 harness 与文档）

- **`wt.py` 拆分**（1140 行 → 4 个文件，`WT_VERSION` 1.4.0）：`wtlib.py`（路径/画像/run/事件/harness.json）、`wtshot.py`（DPI 与 `capture_screen`）、`wtcheck.py`（四份表格解析 + 覆盖/爬取/状态/归因检查 + audit/coverage）、`wt.py`（CLI 与执行类命令）。四份重复的 markdown 表格解析合并的入口留到下一步。
- **状态矩阵**：`ui-map.md` 末尾新增 `## 状态矩阵`，登记「默认/空态/加载中/失败/首次进入…」及到没到；`coverage` 检查它存在、每屏至少一行、S1 至少三行、标「没到」的必须写原因。文档明确：遍历只覆盖**静态可达面**，状态要**用出来**才出现，报告不许写「完整覆盖」。
- **发现必须自证**：每条发现写「归因（产品/脚本/环境/未定）」与「复现次数」，S3/S4 要 2 次以上；`audit` 新增 `finding attribution` 检查。
- **一级入口门禁**：左侧栏每个入口、顶部每个菜单，要么在导航表里有边，要么写够长的原因（只写「不测」不再算数）。
- **遍历可落地**：`shot-window.ps1` 提升进 `harness/`（按窗口截图，并写入 `shot-window` 事件，`audit` 认它），`ui-map.py` 修正导航/状态矩阵的排布与注释误读。
- 平台与模板打磨：`audit` 忽略模板里的 `shots/xx.png` 占位符；`coverage` 在空地图上给爬山提示；`new-run` 模板不再包含空占位节。
- `audit` 修复「假绿」：`shot` 事件没有截图路径、或截图文件已丢失时不再判 PASS；一次截图都没有时直接 FAIL；`click` 后补截图的检查覆盖 `cdp:click*`；新增 `--strict`，WARN 也视为失败，供 CI 使用（默认仍只对 FAIL 退非 0）。
- `cdp.py` 点击目标找不到、或 `eval` 的 JS 抛异常时返回非 0，不再打印一句 `not found` 就退出 0；`--nested` 不再用字符串替换改写表达式（会破坏 `documentElement` 和含 "document" 的字符串字面量）。
- `build-report.py` 正文里 `shots/*.png` 图片内联为 data URI（此前在临时目录的 HTML 里全部 404，PDF 正文没有图）；改用私有 `--user-data-dir`，避免 Chrome 已在运行时打印失败（exit 21）。
- 坐标：`shot` 写出 `<png>.json` 边车（原点 / 缩放 / 尺寸），`click --shot <png>` 按它换算；Windows 截图与点击都声明 DPI 感知；Linux 截图尺寸改为实测（`xdpyinfo`），只在 `software_gl` 为真的 profile 强制软件渲染。
- 脚本健壮性：`ocr.sh` 不再用 `|| true` 吞掉 tesseract 失败；`app-launch.sh` 校验可执行并建 `runtime/`；`desktop-up.sh` 起不来时非 0；`new-run.sh` 转调 `wt.py`；`portal-shot.py` 预推 handle、清理临时文件。
- `preflight` 检查 `chi_sim` 语言包、`xdpyinfo` 与 CDP 依赖；`events.jsonl` / 边车读取容忍 BOM（否则首行解析失败会静默丢事件）。
- `new-run` 预置 `trace/`、`logs/task-trace.txt` 并复制四个模板；`launch --app` 可以不带命令（macOS）。
- 文档与模板对齐：`harness.json` 替代 `meta.json`；S3 补复核字段；任务 trace 补耗时列与 `logs/task-trace.txt` 落点；调研补能力清单与原文摘录；任务矩阵补备注列与实景任务样例。
- **报告可读性**（按 TRAE CN 实跑反馈改）：`report.md` 模板改为「行为先行 → 图 → 为什么算问题 → 建议」，图必须放在对应发现下面；`build-report.py` 的附录改为**可选**（`--appendix`），未引用的截图默认不进 PDF，图号在正文内连续；METHOD 补 5.1 节「让人愿意读」与两条质量清单。
- **截图涂白**：`wt.py report --redact X,Y,W,H`（可重复）与 `captions.json` 的 `redact`（支持 `*` 通配和单图多条）；涂白是改写像素（依赖 Pillow，已加入 `requirements.txt`），不是盖白块——后者能从 PDF 里把原图抠出来。
- `wt.py report` 透传 `--redact` / `--exclude` / `--appendix` / `--max-figure-height`；`click` 默认点击即截图（`--capture` / `--no-capture`），`cdp.py` 新增 `--capture`；`audit` 把「点击自带且文件存在」的截图算作已配对。
- README / INSTALL / METHOD 澄清真实桌面与软件渲染边界：`linux-desktop` 保留 GPU，`linux-x11` 与 `ci` 才走软件渲染；`audit` 只对 FAIL 退非 0。

## v4 — 2026-10-20

- 新增「实景任务执行 trace」：至少 1 个真实项目 / 用户场景，记录 prompt、产物和产品外独立验证。
- 执行阶段必须展开「思考 / 工具调用 / 执行工具 N 次」，记录工具名、命令/参数、结果与耗时；截折叠/展开两张图。
- 报告从六节扩为七节：摘要 / 任务矩阵 / 实景任务执行 / 发现 / 做对了什么 / 方法与限制 / 附录。
- 新增 `templates/task-trace.md`；证据规范增加 `trace/task-trace.md` 与 `logs/task-trace.txt`。
- 质量清单增加实景任务与 trace 两项；本地报告与飞书文档同步补了一个桌面客户端的任务执行 trace 示例。

## v3 — 2026-10-19

- 新增 Step 0 工具调研：先文档后界面，官方说法按「待验证断言」处理；来源分级，产出 `tool-profile.md`。
- 引入 Harness² 的 8 组件骨架与「任务级 / 改进级」两层循环，实例放在 `walkthrough-harness/`。
- harness 增加 `preflight.sh`、`portal-shot.py`；`cdp.py` 支持 `--nth`，按索引点带序号的选项。
- 方法与案例补充：连续任务、权限弹窗「始终允许」复核、安装包 sandbox 权限逐个实测、整屏截图的使用边界。
- 报告固定六节；n=1 与单评分者限制写进交付说明。

## v2 — 2026-10-19

- 从「装一遍、随手点点」改为任务驱动：5–8 个用户任务 + 任务矩阵。
- 严重度统一为 Nielsen 0–4；发现改为「具体元素 + 后果 + 证据 + 建议」。
- 报告改为六节：摘要 / 任务矩阵 / 发现 / 做对了什么 / 方法与限制 / 附录。
- 增加质量检查清单与证据命名规范。

## v1 — 2026-10-19

- 首个版本：隔离 X11 桌面 harness（Xvfb + openbox + 私有 DBus）、截图 / OCR / 点击、报告模板。
- 完成首轮样本走查（配置切换类工具 + CLI），确定「一页摘要 + 问题清单」的交付形态。
