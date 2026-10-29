# Changelog

版本号与 `METHOD.md` 顶部的「方法版本」一致。方法、模板或 harness 有实质改动时升一版；只改案例记录不升版。

## v6.9（2026-10-29，评测人员只读控制台）

- **`code-eval/dashboard/`**：新增本地只读评测控制台模板（原生 HTML/CSS/JS，无第三方依赖）。
  页面包含总览、任务目录、任务详情、运行列表、结果详情、工具 × 任务对比；结果详情展示
  verdict、需求、隐藏验收、scope / quality / claims、diff。
- **`build_dashboard.py`**：从 `runs/*/results/*.json` + `tasks/*.json` 生成 `runs/dashboard/data.js`；
  结果按 `(run, task, rep)` 去重取最新，token 从 result/trace 回填，不上传、不写 runs。
- **输出在 `runs/dashboard/`**，跟 `runs/` 一起 gitignore；模板和用法见 `code-eval/dashboard/README.md`。
- `verify_all.py` 的 Node 语法检查同时覆盖 `harness/webapp_accept.mjs` 和 `code-eval/dashboard/app.js`。

## v6.8（2026-10-29，可用性与可解释性体检）

- **`preflight` 修 agent shell 的假失败**：桌面在跑但没有 `XAUTHORITY` 时，自动尝试
  `/run/user/<uid>/.mutter-Xwaylandauth.*`，PASS 行直接给出要 export 的命令；不再误导用户去启 Xvfb。
- **新增 `verify_all.py`**：一条命令跑单元测试、13 个任务规格、两套自测、Node 语法、Python 编译；
  支持 `--quick`、`--strict`、`--json`。新增 `.github/workflows/verify.yml` 跑同一套检查。
- **文档对齐**：任务数 12 → 13（12 档 + L4b 对照），测试数 97 → 107；补 Node 20+ 与
  `office-eval/requirements.txt`。
- **驱动器不再写死旧版本**：TRAE / Cursor / Qoder 用通用名，Codex 自动读 `codex --version`。
- **记分卡去重**：同一 `(task, rep)` 的重复结果只保留最新文件，不再把一次尝试算两次。
- **任务路由**：13 个任务 JSON 增加 `category` / `complexity` / `tags`；`run_tool.py` 支持
  `--list`、`--category`、`--tag`、`--complexity`、`--min-level`/`--max-level`、`--pick`。
  不写选择器不会再默认跑全量；`--all` 才是全量。测试 107 条。
- 新增 [`AUDIT.md`](AUDIT.md)：这轮体检的范围、证据、已修项和未验证边界。

## v6.7（2026-10-29，验收退出码、并行清理、token 记分）

- **`webapp_accept.mjs` 不再假绿**：此前无论多少 FAIL 都 `exit 0`，CI 和调用方看不到失败；
  现在全过才 0，否则 1（JSON 仍照常写出）。
- **并行安全**：结束时只删本轮 `DB_FILE` 及 `-wal`/`-shm`；原来按 `accept-*.db` 通配，
  会把同一目录下另一个并行任务的库删掉。
- **`report_share.py`**：HTML `<title>` 做转义；`thumbs/a.png` 优先取同级 `a.png`，
  找不到再全目录回退，避免同名图取错。
- **成本进记分卡**：Codex 驱动器记录 `usage`（输入/输出 token），`scorecard.py` 新增 token 列；
  旧结果从 `.trace.jsonl` 回填。L10–L12 复测：L10 667.9k、L11 431.6k、L12 157.1k。
- 测试 102 条（新增 title 转义 1 条）。

## v6.6（2026-10-29，全栈验收归因、报表分享与钉钉单文件）

- **新增 `harness/webapp_accept.mjs`**：TaskFlow 参考验收 43 项。修掉本轮最大的假阳性——`npm run start:api` 的 npm 父进程被 kill 后 node 子进程仍在监听，下一轮健康检查打到上一版服务，出现“全绿但测的是旧代码”。现在每轮随机空闲端口、启动前清端口、唯一 `DB_FILE`、结束 `taskkill /T /F`、清理 `accept-*.db`，并把端口/PID 写进 JSON。
- **验收解析容错**：`Tests N passed` 优先于 `Test Files N passed`；评论 `body`/`content`、活动 `activity`/`activities` 双兼容；RBAC 用种子 admin，不假定首个注册用户是 admin。任何解析失败保留原始输出，不静默通过。
- **新增 `harness/report_share.py`**：一份 Markdown 出三件套——单文件 HTML（base64 原图）、PDF（Chrome/Edge `--print-to-pdf`）、钉钉单文件 MD（`original` 原图 / `compact` 压缩）。`thumbs/` 引用会自动回退到全尺寸原图。
- **METHOD §15**：把本轮踩过的坑固化为规则：验收进程可归因、解析容错、工作区边界（Qoder 把 `walkthrough` 拼成 `workthrough`，在仓外建目录并尝试 `rm -rf`）、截图前台校验、表格缩略图清晰度、钉钉 base64 与原图体积、PDF 分页。
- **METHOD §15.6**：Cursor 订阅拦截记 `blocked` 不记 `failed`；Qoder 压缩上下文后以仓库状态为准；Trae 的“全部保留”人工确认要由驱动识别，避免误判停滞。
- **测试**：新增 `tests/test_report_share.py`（4 条）；`harness/webapp_accept.mjs` 在 Qoder 项目上复跑 **43/43**（随机端口 56069）。

## v6.5（2026-10-29，反作弊收口 + 第一条非 Python 任务）

- **测试装置改动单独判**：`conftest.py` / `pytest.ini` / `tox.ini` / `sitecustomize.py` /
  `usercustomize.py` / `*.pth` 不在 `tests/**` 里，却能改掉 pytest 的收集和跳过行为。
  `grade.py` 现在把这些记成 `scope.harness_tamper`，优先级高于普通 `failed`，出现即
  `scope_violation`。新增两条自测：conftest 全 skip、pytest.ini 取消收集。
- **新任务 L12-async-queue**：Node.js 异步队列，考并发上限、结果顺序、可重试错误预算、
  永久错误不重试；`runner: "node"` 走 `node --test --test-reporter=tap`，TAP 结果按顶层
  测试名解析。任务数 12 → 13，code-eval 不再只有 Python。
- **修判分输出截断**：`run_cmd` 原来只保留最后 4KB，Node 的 8 条验收被截成 6 条，
  前两条静默消失。验收命令改为保留完整输出（结果 JSON 里的 `visible` 仍截断）。
- 自测 45/45；harness 自带测试 97 个，根 README 的旧数字 70 已更正。

## v6.4（2026-10-29，判分从 0/1 变成「完成度 + 可复现」，新加两条难度轴）

- **判分结果升到 schema 2**：新增 `requirements[]` / `score`（每条任务书需求对应哪些隐藏验收、
  满足几条）、`deliverable`（提交后 clone 到干净目录重跑可见测试与隐藏验收）、
  `claims`（交付说明里提到的文件 vs 实际 diff）、`quality.undeclared_imports`。
- **pass 的硬门槛不变**：仍然要隐藏验收全过 + 可见测试全过 + 不碰 `forbidden`；新增字段只增加
  解释力，不放松判定。
- **假阴性修复**：`pytest` 默认关插件自动加载（`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`）。本机
  anyio 插件与 pytest 9.2 冲突，L9 可见测试被环境打断，自测从 31/34 回到 34/34；需要插件的
  任务可在 spec 写 `"pytest_autoload": true`。
- **`outside_allowed` 真正生效**：此前只写进结果、不参与任何判定；现在允许范围外的新增/修改
  会让 `usable=false` 并出现在记分卡上。
- **记分卡按 `level` 字段生成**：修掉 L9 不在硬编码表里显示 `?`、排序错位的问题；新增完成度、
  可复现、逐条需求列。
- **`check_tasks.py` 校验需求映射**：每个隐藏验收必须被某条 requirement 覆盖，每条 requirement
  的测试名必须真实存在；`--strict` 有问题退 1。
- **新任务 L10-stock-reserve**：stdlib HTTP 服务，考并发不超卖、幂等、重启持久化、400/409 语义；
  参考解 7/7，未修改版本 2/7。
- **新任务 L11-report-throughput**：8000 行报表 3 秒预算，考索引/单次遍历与输出一致性；
  未修改版本输出正确但 7.0s 超预算，参考解 6/6。
- 自测 41/41（新增 L10 3 条、L11 3 条、L9「用 conftest 跳过全部验收」1 条，含
  「有幂等但没锁」「小数据对、大数据返回空」两个负例）。
- **OCR 评审后的收口**：`accept_ok` 现在要求 pytest 退出码为 0 且 `passed == total`
  （全 skip/xfail 不再算通过）；`--no-clone` 的交付物检查也核对可见测试；pytest 失败
  摘要保留断言文本；unittest 子测试/`setUpClass` 错误、异步测试、测试名冲突都已覆盖；
  `check_tasks` 的禁区检查按具体 root 匹配，需求映射改成名字边界匹配。

## v6.3（2026-10-28，evidence 与办公判分的四个真 bug）

- **`wt.py evidence` 的位置参数生效**：`evidence --strict runs/<run>` 此前只认 `WALKTHROUGH_RUN`，显式路径被忽略（没设环境变量时直接报「needs a run dir」）。现在 `run_dir` 优先于环境变量。
- **`--shots runs/x/shots` 能读到同层 `captions.json`**：此前只找 `shots/captions.json` 和 `shots/shots/captions.json`，结果每条截图都标「未标注」，`--strict` 假失败。
- **`png_size()` 支持 JPEG**：`evidence` 会 glob `*.jpg` / `*.jpeg`，但尺寸探测只认 PNG，导致合格截图被判 `not-image`。现在按 SOF 段解出宽高。
- **`office-eval/tools/grade.py`**：`--python` 现在真的读 `OFFICE_PYTHON`（文档一直让人设它，代码没读，照做无效）；验收探测超时写成一条失败记录，不再让 `TimeoutExpired` 穿过 `main()`、把 `--out` 一起丢掉。
- 测试：`tests/test_evidence.py` 新增 3 条（JPEG 尺寸、`--shots` 同层 captions、位置参数 run_dir）；共 97 条。

## v6.2（2026-10-28，判分之外的独立评审 + 三处可复现性修补）

- **新增 `code-eval/tools/review.py`**：对一次判分结果里 `changes.added` / `changes.modified` 的文件跑 Alibaba Open Code Review（`ocr scan --format json`），产出 `<result>.review.json`。评审不是判分：`status=unavailable|timeout|error` 时判分结果照旧，没装 ocr 也退出 0。`run_tool.py --review` 可在跑批时顺带打开。
- **L9 干净 clone 可复现**：humanize 的 `src/humanize/_version.py` 是被 vendor 的仓库自己 `.gitignore` 掉的构建产物，clone 下来必然缺失，pytest 收集期就报 `ModuleNotFoundError`。改为在任务规格里声明 `generated`，由 `prepare.py` 写进工作副本（进 baseline 提交，不算 agent 改动）。此前干净 clone 上 code-eval 自测是 31/34，现在是 34/34。
- **`office-eval/tools/selftest.py`**：候选解释器不存在时 `subprocess.run` 抛 `FileNotFoundError`，把整轮自测带崩；改为 `try/except OSError` 跳过、继续试下一个候选。
- 文档：根 README 的版本号从 v5 追到 v6.2；`code-eval/README.md` 删掉两份没有入库的 Qoder / 四家横向报告链接（只留 trae-cn），并补「独立评审」一节。
- 测试：新增 `tests/test_review.py`（5 条：去重、解析、no-changes、ocr 缺失、stub JSON）。

## v6.1（2026-10-28，目标页选择、证据补丁与题面禁区检查）

- **`cdp.py` 目标页选择**：`/json/list` 里常有 `desktop-pet` / 浮层 / 空页排在前面，`pages[0]` 会连错（Qoder 0.4.9：`text` 读出来是空）。新增 `pick_target()` 按 URL 评分：`renderer` / `index.html` 优先，`desktop-pet` / `fixed-surface` / 空页降权；`--match` 仍可强制指定。`tests/test_cdp_pick.py` 覆盖 3 条。
- **`cdp.py` 图标按钮**：`clickel` / `clicktext` 的匹配从只看 `innerText` 扩到 `aria-label` / `title`。Qoder「查看我的用量」这类只有 aria-label 的按钮现在可以直接点。
- **`grade.py` 证据补丁**：`git status` / `git diff` 排除 `__pycache__`、`*.pyc`、`*.pyo`；补丁里不再出现二进制缓存 hunk，改动清单也不会被缓存文件撑大。
- **`check_tasks.py`**：新增题面 / 禁区一致性检查。`forbidden: tests/**` 但题面没有「不要改 tests/」时 WARN，`--strict` 退 1。现存 L2、L3 两条警告——这是题面漏写，不是 agent 越界。
- 测试：新增 `tests/test_cdp_pick.py`（3 条）；`code-eval/tools/selftest.py` 34/34。

## v6.0（2026-10-27，证据工作簿校验）

- **新增 `harness/xlsx_audit.py`**：检查同一图片跨格复用、图片超出单元格、Excel 行高超过 409.5pt、`未查到/无` 缺少【缺失证据】、`有` 误用缺失证据。
- **新增 `tests/test_xlsx_audit.py`**：覆盖 clean book、复用图、行高超限、图片超高、缺失证据标注、状态冲突。
- **METHOD.md §14 证据工作簿硬规则**：一图一格、图内不画标注、行高/列宽换算、多屏左右并排、看图后再写 caption。
- 背景：Codex/TRAE 批量表出现一张 help 图被 9–13 行复用、图内 caption 挡内容、行高超过 Excel 上限导致图片溢出。

## v5.9 — 2026-10-26（证据可读性与归因）

- **METHOD §8.1 证据可读性与归因**：最小可读尺寸（报告 ≥800×400，单元格 ≥420×210）、裁到控件、每图标证据类型、账号/额度限制不进问题清单、同屏证据要标注、没有独立截图就写「无独立截图」、截完先自检。
- **METHOD §9.1 多 Electron 窗口**：同名「Agent」窗口会抓错图；记录 `hwnd + pid + title + rect`、必要时最小化其它窗口、focus 后仍超时先查遮挡；`prepare --force` 前先释放工作区占用（Cursor 的 `.git/cursor/crepe/index.bin`）。
- **`templates/report.md`**：头部增加「测试账号 / 套餐 / 额度」；问题模板与 backlog 增加「证据类型」字段。
- **`templates/tool-profile.md`**：事实卡增加「测试账号 / 套餐 / 额度」。
- **`walkthrough-harness/tool_descriptions/tool_guidance.md`**：新增「Screenshots and attribution」一节，覆盖裁剪、尺寸、证据类型、账号/额度归因、同屏证据、空白页、窗口遮挡、重绘卡。
- **`code-eval/tools`**：补 `drive_cursor.py`（CDP + ProseMirror）、`drive_codex.py`（`codex exec --json` / `resume --last`）、`run_tool.py`（`--driver --tasks --reps --run --force`）。
- **`wt.py evidence`**：扫描 `shots/` / `screens/` 或 `--cells` CSV，检查尺寸（默认 ≥800×400）、`evidence.json` / `captions.json` 里的证据类型；`--strict` 对低分辨率、未标注、非图片返回 1；空文件输出 `无独立截图`（`no-shot`），不生成假图。
- **`cdp.py shot` 尺寸自检**：保存后打印 `WxH`，低于 800×400 直接 WARN，提示裁到控件或放大窗口。
- **`code-eval/tools/preflight.py`**：检查账号/额度/同名窗口；Cursor/Qoder/Trae 走 CDP 文本标记，Codex 读 `codex --version` 与 `~/.codex/config.toml`；`blocked` 退出 2。
- **`run_tool.py` / `run_suite.py --preflight`**：读 preflight JSON，`blocked` 时在跑任务前退出 2，避免把额度/账号问题记成 `failed`。
- **测试**：新增 `tests/test_evidence.py`（尺寸、metadata、no-shot）与 `tests/test_preflight.py`（quota/账号标记）；现有 80 条 harness 测试通过。

## v5.8 — 2026-10-26（Qoder CN 之后，把踩过的坑收回 harness）

- **launch 剥离 `ELECTRON_RUN_AS_NODE`**：agent 宿主常把它导出给子进程，Electron 应用会退化成 Node——启动即退出（exit 9）、`--version` 打出 Node 版本、CDP 端口永不打开。`wt.py launch` 现在对子进程移除并打印一行说明；`preflight` 发现该变量时 WARN。（Qoder CN 0.4.9 第一轮就栽在这里。）
- **新增 `wt.py focus <进程名>`**：Chromium 会节流被遮挡的窗口，`cdp.py text` 仍可用但 `cdp.py shot` 会超时。Windows 用 `harness/focus.ps1`（ShowWindow + SetForegroundWindow），macOS 用 AppleScript，Linux 用 `xdotool windowactivate`。
- **launch 的默认日志路径**：`/tmp/...` 在 Windows 上会落到 `D:\tmp`，改用 `tempfile.gettempdir()`。
- **METHOD §9 补四条 Electron 经验**：先清 `ELECTRON_RUN_AS_NODE`、遮挡先 focus、原生菜单不在 DOM/UIA 里、审批可能是 split button（点主体只展开菜单）。
- **METHOD §8 补证据命名**：`events.jsonl` 按绝对路径记截图，截完别改名；要改编号就留旧名别名，不要回头改日志。
- **`harness/pick-folder.ps1`**：把 Qoder 那次写的原生文件夹选择器助手从 `code-eval/tools` 挪进 harness（按进程 + `#32770` 找窗口，`WM_SETTEXT` 填路径，`BM_CLICK` 点确认），任何走查都能复用。
- **`walkthrough-harness` 文档**：`tool_guidance.md` 增加 Windows 环境、原生菜单/审批、证据路径三节；`scripts/README.md` 登记 `focus.ps1` 与 `pick-folder.ps1`；新增 `tests/test_launch_env.py`（4 条）。
- 版本对齐：`METHOD.md` 头部停在 v5.3 而 changelog 已到 v5.7，这次一并更新到 v5.8。

## v5.7 — 2026-10-23（全量 review 后的修补）

- **Python 3.9 兼容**：`prepare.py` 的 `shutil.rmtree(onexc=...)` 只有 3.12+ 支持，改成带 `onerror` 回退的包装（README 一直写的是 3.9+）。
- **git 兜底统一**：`find_git()` 收进 `snap.py`，`prepare.py` 与 `grade.py` 都用它；此前 PATH 里没有 git 时，baseline 和 `git diff` 会被静默跳过，补丁里就少了「修改过的文件」。
- **办公判分的前置检查**：`office-eval/tools/grade.py` 先确认 `--python` 能 `import openpyxl`，否则直接报错退出，而不是判成「产物不合格」。
- **自测不再写宿主 temp**：`office-eval` 的自测根目录挪到 `office-eval/.selftest-tmp`，和 `code-eval` 一致（workspace-write 沙箱下宿主 temp 不可写）。
- **死代码与未用 import**：删掉 `drive_trae.py` 里没人调用的 `approve()` 分支（改为复用），清掉 `cdp.py`、`test_coverage.py`、`selftest.py` 的未用 import。
- **记分卡不再写死 3 列**：按实际最大 rep 生成表头。
- 文档对齐：`code-eval/README` 的 L1–L6 → L1–L9、用例数 15 → 34；根 README 的「不包含什么」改成 9 个任务 + 办公现状。

## v5.6 — 2026-10-23（真实开源仓库）

- **L9-humanize-intword**：拿 [humanize](https://github.com/python-humanize/humanize)（MIT）修复提交 `ca892b3` 的父提交做 fixture，隐藏验收用上游自己的回归测试 `test_intword_rounding_rollover`，题面只给症状（`10**24-1` 渲染成 `1000.0 sextillion`）。这是第一个「代码不是我写的、bug 不是我埋的、测试不是我写的」任务。
- **pytest 支持**：spec 新增 `"runner": "pytest"` 与 `"pythonpath": "src"`；`grade.py` 用 `CODE_EVAL_PYTHON` 指定的解释器跑验收，输出折成和 `accept_run.py` 一样的 JSON。
- **判分沙箱化**：判分子进程的 `TEMP/TMP/TMPDIR` 指到本轮目录下的 `.eval-tmp`；`selftest` 的临时根也从系统 temp 挪到 `code-eval/.selftest-tmp`。宿主 temp 在 workspace-write 沙箱里不可写时，验收里的 `TemporaryDirectory` 会直接报「No usable temporary directory」。
- 真实数据：L9 三次都是第 1 轮过，改 5–10 行（上游修复是 8 行）；耗时 94–292 秒，第一次跑了整仓测试。

## v5.5 — 2026-10-23（场景 3：存量工程 + 两个新指标）

- **L8-payments-idem**：一个多模块支付仓库，三处必须一起改的 bug——幂等键带了时间戳、金额换算用 `int()` 截断、超时重试换了新键。6 条隐藏验收覆盖重复请求、超时重试、金额 half-up、重放一致性；只修一处的变体判失败。
- **`--max-rounds`**：不通过就把隐藏验收的失败摘要（测试名 + 最后一行断言，不给源码）喂回去继续修，`rounds_to_pass` 记第几轮过。默认 1 轮，等于不重试。
- **`quality.usable`**：通过且没在 `allowed` 之外新建文件、补丁里没有 `TODO/FIXME/breakpoint/pdb` 才算「结果能直接用」。`grade.py` 的 patch 现在会补上未跟踪的新文件（`git diff` 不含它们，之前新增的调试文件在判分里是隐形的）。
- 真实数据：L8 三次都是第 1 轮过、每次约 16 行、可用为 true；跨文件一致性没有变成门槛。

## v5.4 — 2026-10-23（不抢输入 + 两条新轴）

- **走查可以不抢用户的鼠标键盘**：新增 `WALKTHROUGH_NO_NATIVE_INPUT=1`（或单次 `click --no-native-input`），`wt.py click` 会直接拒绝并提示改用 `cdp.py`；`preflight` 打印当前模式。除了 `click`（Windows `SetCursorPos` / macOS `cliclick` / Linux `xdotool`），截图、OCR、`launch`、CDP 驱动的点击与输入都不注入系统输入。README / INSTALL / METHOD 各补了一段。
- **L7 大仓库**：新增 `make_large_fixture.py` 生成 128 个 Python 文件的账单服务，真实 bug 在一个导出器里，另外两个旧版导出器做诱饵；隐藏验收覆盖作废单保留、列顺序、金额格式与行序。
- **`office-eval/`**：办公产物判分（实验）。O1 任务从 CSV 生成 xlsx（两个 sheet、环比 %、合计行），9 条 openpyxl 隐藏验收；`tools/grade.py` 检查禁区并跑验收，`tools/selftest.py` 用参考产物 + 3 个错误变体验证口径（5/5）。docx 任务待加。

## v5.3 — 2026-10-23（定位调整：决策材料 → 问题清单）

- **报告的骨架从「决策摘要 + 前三问题」换成「问题总览 + 全量问题清单」**：删掉「建议动作（上线 / 整改后上线 / 试点）」和「决策问题」字段，改成「评测范围 / 不在范围」；「前三问题」降为总览里的一个排序视图。理由：决策框架要求前三条展开、其余压成一句话，第 4 条起复现细节就丢了，而这正是「发现问题」最需要的内容。
- **每条问题新增三个必填字段**：影响面、最小复现、置信度（已复核 / 单次 / 推断）。backlog 表同样要有这三列。这样问题数量增长不会变成噪音——数量涨是因为每条都可验证，而不是因为报得多。
- `templates/report.md` 从 7 节改为 6 节（问题总览 / 覆盖与任务矩阵 / 实景任务 / 问题清单 / 已验证正常的行为 / 方法与限制 + 附录）；「做对了什么」改名「已验证正常的行为」，作用改为防止返工时误改，不再是决策佐证。
- Step 2「定决策」改为「定评测范围」：覆盖哪些能力域 / 界面 / 任务类型、不覆盖什么及原因。`task-plan.md`、`tool-profile.md` 的抬头字段同步。
- `systemprompt.md`：交付物从「决策材料」改为「问题清单」；新增「不要一边记录一边过滤」——先记成问题再分级，不确定的标「推断」，而不是不写。
- **`audit` 新增两项硬检查**（WARN 级）：`problem summary`（报告必须有「问题总览」一节）；`finding attribution` 现在要求每条问题都有 归因 / 复现 / 置信度 / 最小复现 四个字段。
- 质量清单同步：「写清了决策问题与读者」→「写清了评测范围与不在范围」；「摘要 5 分钟内做出决定」→「问题总览 5 分钟内看清有哪些问题、多严重、多可信」。

## v5.2 — 2026-10-22（不改流程：git 变成显式依赖）

- **`preflight` 检查 git**：读 `harness.lock` 的 `git_min`（默认 2.20），capabilities 行输出 `git` / `git:unavailable`；`harness/preflight.sh` 的 host dependencies 也算 git。
- **`find_git()` 先找安装位置、再看 PATH**：Windows 装完 Git 后，长驻的父进程环境还是旧的，只查 PATH 会误报 missing；常见路径（`C:\Program Files\Git\cmd`、Homebrew、`/usr/local/bin`）都会被找到，也可以用 `WALKTHROUGH_GIT` 指定。`git` 仍是 WARN 级——没有它，界面走查照跑，`new-run.sh`、钩子和后面的改动判分才需要。
- **新增 `code-eval/`（实验）**：四个难度档的任务（单文件修 bug / 多文件加功能 / 跨模块排错 / 六文件时区与汇率排错）+ 一个只给症状不给规则的对照、每个任务一份不进 agent 上下文的隐藏验收、`prepare → 改动 → grade` 判分链路（用 git baseline + `git diff` 取改动，快照兜底）、TRAE Agent 的 CDP 驱动器、批量跑与记分卡。`tools/selftest.py` 用 15 个假 agent 用例验证口径：正确解通过、只讨好可见用例的不通过、改 `tests/**` 判 `scope_violation`、只修一半的不通过。

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
