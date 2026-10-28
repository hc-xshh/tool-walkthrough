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
  tools/          prepare / snap / grade / accept_run / drive_trae / drive_qoder / drive_cursor / drive_codex / preflight / run_tool / run_suite / check_tasks / scorecard / timing / regrade / selftest
  selftest/       假 agent 的参考解与负例，用来验证判分口径
  reports/        跑完的报告（可提交，不含证据原文件）
  runs/           本地产物（不在本目录，见仓库根的 .gitignore）
```

已有结果：[`reports/2026-10-22-trae-cn.md`](reports/2026-10-22-trae-cn.md)（TRAE CN 3.4.4，L1–L9 各 3 次）、[`reports/2026-10-26-qoder-cn.md`](reports/2026-10-26-qoder-cn.md)（Qoder CN 0.4.9，L1–L9 各 3 次，29/30）、[`reports/2026-10-26-four-tools.md`](reports/2026-10-26-four-tools.md)（四家横向：Trae / Qoder / Cursor / Codex）。

## 口径

一次尝试的 `verdict`：

| 判定 | 含义 |
|---|---|
| `pass` | 隐藏验收全过 + 可见测试全过 + 没碰禁区 |
| `failed` | 隐藏验收有失败（可见测试可能也过） |
| `visible_tests_failed` | 连仓库原有测试都没跑通 |
| `scope_violation` | 改了 `forbidden` 路径（默认 `tests/**`） |

「可见测试」是 fixture 自带的测试；它只是地板，不是验收。真正的分在隐藏验收：
边界值、非法入参、不变量、回归。

**每条隐藏验收必须能对到任务书的一句话**。对不上的，删掉，或者补进任务书——否则判分器会
制造「假阴性」，看起来是工具不行，其实是题出得不公平（L5 的 `deleted` 计数踩过一次）。

## 两个额外指标：几轮改对、能不能直接用

- **轮次**：`max_rounds` 控制。第一轮不过就把隐藏验收的失败摘要（只给测试名和最后一行断言，
  不给测试源码）喂回去让它继续修；`rounds_to_pass` 记第几轮过。没配置时默认 1 轮，等于不重试。
- **可用**：`quality.usable` = 通过 **且** 没在 `allowed` 之外新建文件 **且** 补丁里没有
  `TODO / FIXME / XXX / breakpoint() / pdb`。通过但留了调试文件的，记 pass 但 usable 为 false。
  未跟踪的新文件也要算进 patch——`git diff` 不含它们，`grade.py` 会用快照补上。

```bash
python tools/drive_trae.py --task L8-payments-idem ... --max-rounds 3
```

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
python code-eval/tools/selftest.py     # 34 个假 agent 用例，覆盖正确/偷懒/越界/只修一半
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

- 判分假设 agent 只改文件系统；绕过测试（改 `conftest.py`、`sitecustomize.py`、
  写 `pytest.ini`）靠 `forbidden` 拦住，但只拦得住列出来的路径。
- `timebox_s` 到了就判失败，超时本身是结论的一部分。
- 三个任务只能说明「这三个任务」，不能外推成「编程能力」的总评。
