# code-eval — 编码能力判分（实验）

判分的是 **agent 交出的代码**，不是界面。同一份任务书 × 多次重复 × 隐藏验收，
得出「这一版能不能推给团队」需要的数字。体验走查仍在本仓根目录的 `METHOD.md`。

## 为什么单独一套

| | 体验走查（METHOD.md） | 能力判分（这里） |
|---|---|---|
| 被测对象 | 界面与流程 | 改动后的代码 |
| 证据 | 截图 / 页面地图 | diff / 隐藏测试结果 |
| 样本 | n=1 合法（第一遍观感只有一次） | n≥3（agent 有采样随机性） |
| 结论 | 先修哪三件 | 通过率、成本、失败模式 |
| 判分 | 人 | 脚本（验收不在 agent 上下文里） |

## 目录

```
code-eval/
  tasks/          任务书（给 agent 的 prompt）+ 任务规格（allowed / forbidden / 验收）
  fixtures/       每个任务的起始仓库（agent 在副本上工作）
  accept/         隐藏验收，判分时才拷进工作目录，agent 看不到
  tools/          prepare / snap / grade / accept_run / drive_trae / run_suite / scorecard / timing / regrade / selftest
  selftest/       假 agent 的参考解与负例，用来验证判分口径
  reports/        跑完的报告（可提交，不含证据原文件）
  runs/           本地产物（不在本目录，见仓库根的 .gitignore）
```

已有结果：[`reports/2026-10-22-trae-cn.md`](reports/2026-10-22-trae-cn.md)（TRAE CN 3.4.4，5 个任务 × 3 次）。

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
python code-eval/tools/selftest.py     # 15 个假 agent 用例，覆盖正确/偷懒/越界/只修一半
```

## 四个档位

| 任务 | 档 | 考什么 | 陷阱 |
|---|---|---|---|
| `L1-split-bill` | L1 | 单文件修 bug，金额拆分不丢分 | 只让可见用例通过（硬编码）会失败 |
| `L2-todo-due` | L2 | 多文件加功能：日期存取、筛选、done 子命令、退出码 | 功能做了但不校验日期格式 |
| `L3-sales-pipeline` | L3 | 跨模块三处缺陷：half-up 舍入、退款保留、transform 顺序 | 只修舍入，退款和顺序没动 |
| `L4-monthly-ledger` | L4 | 6 个文件里找三处错：时区归月、周末汇率、重复导出 | 只修时区、去重保留旧值、按 UTC 归月 |
| `L4b-ledger-ambiguous` | L4 对照 | 同一仓库，只给症状不给规则 | 推断不出「自有时区 / 交易日回溯 / amend 覆盖」就失败 |

## 加一个任务

1. `fixtures/<id>/repo/`：起始仓库 + 自带测试（要能跑）。
2. `accept/<id>/test_accept.py`：隐藏验收，只依赖标准库和被测模块。
3. `tasks/<id>.json`：`fixture` / `accept` / `prompt` / `allowed` / `forbidden` / `visible` / `timebox_s`。
4. `tasks/<id>.prompt.txt`：任务书，路径用 `{workdir}` 占位。
5. 在 `tools/selftest.py` 加「参考解通过」和「偷懒不通过」两条用例，再跑一遍自测。

## 边界

- 判分假设 agent 只改文件系统；绕过测试（改 `conftest.py`、`sitecustomize.py`、
  写 `pytest.ini`）靠 `forbidden` 拦住，但只拦得住列出来的路径。
- `timebox_s` 到了就判失败，超时本身是结论的一部分。
- 三个任务只能说明「这三个任务」，不能外推成「编程能力」的总评。
