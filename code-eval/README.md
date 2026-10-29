# code-eval — 编码能力判分（实验）

判分的是 **agent 交出的代码**，不是界面。同一份任务书 × 多次重复 × 隐藏验收，
得出「这一版能不能推给团队」需要的数字。体验走查仍在本仓根目录的 `METHOD.md`。

## 为什么单独一套

| | 体验走查（METHOD.md） | 能力判分（这里） |
|---|---|---|
| 被测对象 | 界面与流程 | 改动后的代码 |
| 证据 | 截图 / 页面地图 | diff / 隐藏测试结果 |
| 样本 | n=1 合法（第一遍观感只有一次） | n≥3（agent 有采样随机性） |
| 交付 | 问题清单：严重度 × 置信度、每条带最小复现 | 失败模式：哪类任务会错、错在哪、稳不稳定 |
| 判分 | 人 | 脚本（验收不在 agent 上下文里） |

## 目录

```
code-eval/
  tasks/          任务书（给 agent 的 prompt）+ 任务规格（allowed / forbidden / 验收）
  fixtures/       每个任务的起始仓库（agent 在副本上工作）
  accept/         隐藏验收，判分时才拷进工作目录，agent 看不到
  tools/          prepare / snap / grade / accept_run / drive_trae / drive_qoder / drive_cursor / drive_codex / preflight / run_tool / run_suite / check_tasks / scorecard / timing / regrade / review / selftest
  selftest/       假 agent 的参考解与负例，用来验证判分口径
  reports/        跑完的报告（可提交，不含证据原文件）
  runs/           本地产物（不在本目录，见仓库根的 .gitignore）
```

已有结果：[`reports/2026-10-22-trae-cn.md`](reports/2026-10-22-trae-cn.md)（TRAE CN 3.4.4，L1–L9 各 3 次）、
[`reports/2026-10-29-codex-l10-l12.md`](reports/2026-10-29-codex-l10-l12.md)（Codex CLI 0.163.0 / deepseek-flash，
L10–L12 各 3 次，9/9 通过）。Qoder CN 0.4.9 与四家横向（Trae / Qoder / Cursor / Codex）也跑过，但那两份报告没有入库，只在本机 `runs/` 下——不要当成可引用的公开结论。

## 口径

一次尝试的 `verdict`：

| 判定 | 含义 |
|---|---|
| `pass` | 隐藏验收全过 + 可见测试全过 + 没碰禁区 |
| `failed` | 隐藏验收有失败（可见测试可能也过） |
| `visible_tests_failed` | 连仓库原有测试都没跑通 |
| `scope_violation` | 改了 `forbidden` 路径（默认 `tests/**`） |
| `timeout` | 超过时限，没做完；不计入能力结论 |
| `blocked` | 账号 / 额度 / 窗口不可用，本轮没测成；不计入能力结论 |

「可见测试」是 fixture 自带的测试；它只是地板，不是验收。真正的分在隐藏验收：
边界值、非法入参、不变量、回归。

**每条隐藏验收必须能对到任务书的一句话**。现在这条由 `tasks/*.json` 的
`requirements` 机械保证：`check_tasks.py` 会检查每个验收测试都被某条需求覆盖、
每条需求的测试名都真实存在，`--strict` 有问题直接退 1。对不上的验收会造成
「假阴性」——看起来是工具不行，其实是题出得不公平（L5 的 `deleted` 计数踩过一次）。

## 四个额外指标：几轮改对、完成了几条、能不能直接用、能不能复现

- **轮次**：`max_rounds` 控制。第一轮不过就把隐藏验收的失败摘要（只给测试名和最后一行断言，
  不给测试源码）喂回去让它继续修；`rounds_to_pass` 记第几轮过。没配置时默认 1 轮，等于不重试。
- **完成度**：`score` = `requirements` 里满足的条数 / 总条数（0–1）。全过才算 `pass`，
  但「6 条里过了 5 条」现在能看见，而不是只剩一个 ❌。每条需求对应哪些隐藏验收写在任务
  JSON 里；`grade.py` 按测试名匹配，缺测试或测试没跑也算未满足。
- **可复现**：`deliverable`。把 agent 的改动提交后 `git clone` 到干净目录，重跑可见测试与
  隐藏验收。只活在本机未跟踪文件、绝对路径、漏写依赖的交付物，原地判分会过，干净副本会失败。
  结果不进 verdict（原地验收仍是判分依据），进 `usable` 与记分卡的「可复现」列。
- **可用**：`quality.usable` = 通过 **且** 没在 `allowed` 之外新建/修改文件 **且** 补丁里没有
  `TODO / FIXME / XXX / breakpoint() / pdb`。通过但留了调试文件的，记 pass 但 usable 为 false。
  未跟踪的新文件也要算进 patch——`git diff` 不含它们，`grade.py` 会用快照补上。
- **交付说明对账**：`claims`。题面要求「说明改了哪几个文件」，驱动器把最终回复传给
  `grade.py --final-message`；它抽出提到的文件路径，和实际 diff 对账。不参与 verdict，
  只回答「交付说明有没有虚报」。CLI 驱动器现在会写 `<result>.final.md`；UI 驱动器暂未接。
- **依赖声明**：`quality.undeclared_imports`。补丁里新 import 的第三方模块，如果不在
  `requirements*.txt` / `pyproject.toml` / 本仓库目录里，记一条。静态检查，不联网。

```bash
python tools/drive_trae.py --task L8-payments-idem ... --max-rounds 3
python tools/grade.py --task L1-split-bill ... --no-clone        # 跳过干净副本检查
python tools/grade.py --task L1-split-bill ... --final-message out.final.md
```

判分器自身也要能自证：`pytest` 默认关闭插件自动加载（`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`），
避免宿主全局插件（anyio 等）把隐藏验收弄成假失败；确实需要插件的任务在 spec 里写
`"pytest_autoload": true`。

### 多语言 runner

`tasks/*.json` 的 `runner` 决定隐藏验收怎么跑：

- 不写 / `"unittest"`：`accept_run.py` 跑标准库 `unittest`（Python 默认）
- `"pytest"`：`python -m pytest -v`（真实仓库任务用）
- `"node"`：`node --test --test-reporter=tap _accept/test_accept.test.js`，TAP 结果按顶层
  测试名解析；需要多个文件时在 spec 里写 `accept_cmd`

`L12-async-queue` 是第一条非 Python 任务：Node 22 + `node:test`，零第三方依赖。
它同时验证了判分器不是只会读 Python 的 `unittest` 输出。

### 反作弊：测试装置的改动单独判

`tests/**` 由 `forbidden` 拦；但根目录的 `conftest.py`、`pytest.ini`、`tox.ini`、
`sitecustomize.py`、`usercustomize.py`、`*.pth` 不在 `tests/` 下，却能改掉收集和跳过行为。
`grade.py` 现在把它们单独记成 `scope.harness_tamper`，**优先级高于普通 failed**：
出现即 `scope_violation`，原因写明改了哪个文件。对应自测用例：
「用 conftest 跳过全部验收」「用 pytest.ini 取消收集」。

## 独立评审：改得怎么样（可选，不参与判分）

判分回答「过没过」，评审回答「改得怎么样」。用 Alibaba 开源的 Open Code Review（命令名 `ocr`）对 agent 改过的文件再跑一遍：

```bash
# 装一次
npm i -g @alibaba-group/open-code-review
ocr config set provider deepseek      # 也可以 openai / anthropic / 自定义兼容端点
ocr llm test

# 对一次已判分的结果做评审
python code-eval/tools/review.py --result runs/<run>/results/L1-r1.json

# 批量跑的时候直接开
python code-eval/tools/run_tool.py --driver drive_codex.py ... --review
```

- 产物是 `<result>.review.json`：`comments[]`（文件 / 起止行 / 意见 / 建议补丁）+ `summary`（token、耗时）。
- **它不改变 verdict**。评审跑失败只记 `status=unavailable|timeout|error`，判分结果照旧；没装 `ocr` 也退出 0——「评审工具没装」不是「这次尝试有问题」。
- 只审 `changes.added` + `changes.modified` 里出的文件，用 `ocr scan`（整文件、不需要提交），所以会连带看到该文件里的既有问题，不只是这次改动。要只审本次 diff，得先把 agent 的改动提交成一次 commit，再 `ocr review --commit`。
- 用途是横向比较多一层：同一任务，过没过是一层，「被独立评审挑出几条、挑的是不是真问题」是另一层。**条数不是能力分**，误报要人看。

## 证据与归因（2026-10-26 补）

- 代码判分的证据是 **diff + 隐藏验收输出**，不是界面截图；`scope_violation` 不等于「作弊」——先看它改的是不是回归测试，再下结论。
- 跑之前记录账号 / 套餐 / 额度 / provider。免费额度用尽、账号不能用某个模型、未登录，都是 **未测**，不是 `failed`；这些只能进报告的限制，不能写成产品缺陷。
- 通用驱动：`run_tool.py --driver drive_cursor.py|drive_codex.py --tasks ... --reps 3 --run <dir>`；Cursor 走 CDP/ProseMirror，Codex 走 `codex exec --json` + `resume --last`。
- `prepare.py --force` 前先关掉被测应用对该 workdir 的占用；Cursor 会锁 `.git/cursor/crepe/index.bin`，锁住时换新 workdir，不要反复重试删除。
- 跑批前先做 preflight：
  ```bash
  python code-eval/tools/preflight.py --tool cursor --port 9562 \
      --out runs/<run>/preflight.json
  python code-eval/tools/run_tool.py --driver drive_cursor.py ... \
      --preflight runs/<run>/preflight.json
  ```
  `blocked`（额度用尽 / 账号不能用模型 / 抓错窗口）会退出 2，run_tool 不会启动任务。
- 跑批前先检查「题面写没写禁区」：
  ```bash
  python code-eval/tools/check_tasks.py          # 只 WARN
  python code-eval/tools/check_tasks.py --strict # 有警告退 1，CI/跑批用这个
  ```
  `forbidden` 里的 `tests/`、`data/` 必须在 prompt 里用「不要改 …」写明；否则 agent 没被告知，判 `scope_violation` 会把题面漏写记成产品越界。

## 跑一次

```bash
# 1. 准备干净副本（打 baseline 提交 + 记录改动前快照）
python code-eval/tools/prepare.py --task L1-split-bill \
    --workdir runs/<run>/work/L1-r1 --force

# 2. 让被测工具在 workdir 里干活（模型、IDE、CLI 都行）
#    要自动化 TRAE，用：
python code-eval/tools/drive_trae.py --task L1-split-bill \
    --workdir runs/<run>/work/L1-r1 --rep 1 \
    --out runs/<run>/results/L1-r1.json --prepare --force

# 3. 判分（drive_trae 会自动调；手工跑时用这个）
python code-eval/tools/grade.py --task L1-split-bill \
    --workdir runs/<run>/work/L1-r1 \
    --before runs/<run>/work/L1-r1.before.json \
    --rep 1 --tool "..." --duration 42 \
    --out runs/<run>/results/L1-r1.json

# 4. 出记分卡（耗时按 trace 里「提交 → 界面最后一次变化」重算）
python code-eval/tools/timing.py --run runs/<run>
python code-eval/tools/scorecard.py --run runs/<run>
```

判分口径改了、想补 patch 与改动行数时，不用重跑 agent：

```bash
python code-eval/tools/regrade.py --run runs/<run>
```

整套自测（不需要被测工具）：

```bash
python code-eval/tools/selftest.py     # 45 个假 agent 用例，覆盖正确/偷懒/越界/只修一半
```

## 任务清单

| 任务 | 档 | 考什么 | 陷阱 |
|---|---|---|---|
| `L1-split-bill` | L1 | 单文件修 bug，金额拆分不丢分 | 只让可见用例通过（硬编码）会失败 |
| `L2-todo-due` | L2 | 多文件加功能：日期存取、筛选、done 子命令、退出码 | 功能做了但不校验日期格式 |
| `L3-sales-pipeline` | L3 | 跨模块三处缺陷：half-up 舍入、退款保留、transform 顺序 | 只修舍入，退款和顺序没动 |
| `L4-monthly-ledger` | L4 | 6 个文件里找三处错：时区归月、周末汇率、重复导出 | 只修时区、去重保留旧值、按 UTC 归月 |
| `L4b-ledger-ambiguous` | L4 对照 | 同一仓库，只给症状不给规则 | 推断不出「自有时区 / 交易日回溯 / amend 覆盖」就失败 |
| `L5-notes-sync` | L5 | 长任务：冲突合并、墓碑、幂等、事务、旧账本兼容 | 不看墓碑会复活、不校验输入会写坏账本 |
| `L6-notes-soft-delete` | L6 | 多轮：先按 L5 实现同步，再追加一轮把物理删除改成软删除 | 第二轮没做、没迁移旧墓碑、把第一轮规则改坏 |
| `L7-billing-export` | L7 | 128 个文件里定位真正的导出器，作废单不能丢 | 改旧版导出器、只保留列不加标记、金额格式错 |
| `L8-payments-idem` | L8 | 存量工程：幂等键、金额换算、超时重试三处必须一起改 | 只修一处、换键重试、int 截断金额 |
| `L9-humanize-intword` | L9 | 真实仓库（humanize）+ 上游真实回归测试 | 浮点比较残留、只改 `%.0f` 分支 |
| `L10-stock-reserve` | L10 | HTTP 服务：并发预占、幂等、重启持久化、入参校验 | 先读后写不超卖、重试重复扣、重启后预占丢失 |
| `L11-report-throughput` | L11 | 性能预算：8000 行报表 3 秒内，输出逐字段不变 | 全量重算 O(n²)、只优化小数据路径 |
| `L12-async-queue` | L12 | Node.js 异步队列：并发上限、结果顺序、重试预算 | 一次全发、按完成顺序 push、所有错误都重试 |

多轮任务在 spec 里用 `prompts` 数组代替 `prompt`，驱动器在**同一个会话**里依次发送（不新建任务），
最后统一判分；每轮单独等 idle，上一轮的「任务耗时」不能当完成信号。

**真实仓库任务**（`L9`）来自开源项目 [humanize](https://github.com/python-humanize/humanize)（MIT），
fixture 是修复提交 `ca892b3` 的父提交，隐藏验收是上游的 `test_intword_rounding_rollover`。
这类任务在 spec 里写 `"runner": "pytest"` 和 `"pythonpath": "src"`：验收用 pytest 跑，
`CODE_EVAL_PYTHON` 指向装了 pytest 的解释器（系统 Python 一般没有）：

```bash
export CODE_EVAL_PYTHON=/path/to/venv/bin/python
python tools/drive_trae.py --task L9-humanize-intword ... 
```

## 加一个任务

1. `fixtures/<id>/repo/`：起始仓库 + 自带测试（要能跑）。
2. `accept/<id>/test_accept.py`：隐藏验收，只依赖标准库和被测模块。
3. `tasks/<id>.json`：`fixture` / `accept` / `prompt` / `allowed` / `forbidden` / `visible` / `timebox_s`。
4. `tasks/<id>.prompt.txt`：任务书，路径用 `{workdir}` 占位；`forbidden` 里的 `tests/`、`data/` 必须在题面里用「不要改 …」写明。
5. 在 `tools/selftest.py` 加「参考解通过」和「偷懒不通过」两条用例；再跑 `python tools/check_tasks.py --strict` 与一遍自测。

## 边界

- 判分假设 agent 只改文件系统。`conftest.py` / `pytest.ini` / `sitecustomize.py` 等
  测试装置改动现在直接判 `scope_violation`；但仍拦不住所有花招——比如在允许改的文件里
  动态篡改 `sys.modules`，或依赖网络/全局状态。
- `timebox_s` 到了记 `timeout`，不算 `failed`：没做完和做错了是两件事。
- 干净副本检查只覆盖「仓库自身可复现」；宿主环境（Python/Node 版本、系统库）不在检查范围内。
- 这些任务只能说明这几类任务，不能外推成「编程能力」的总评；L10/L11 覆盖服务并发与
  性能预算，L12 开始覆盖 Node.js 异步语义，但整体仍以 Python 为主。
