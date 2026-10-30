# 维度 · 场景 · 运行 · 报告

- 状态：已实施（2026-10-30）
- 取代：工作台上的「走查 / 评测」两个入口（底层能力保留为采集器）

## 1. 为什么改

原来的两条线各自回答一个问题，但都不回答「**这个产品在某个能力维度上表现如何**」：

| 线路 | 回答 | 问题 |
|---|---|---|
| 走查 | 界面在哪儿挡住人 | 看不见代码交付得好不好 |
| 评测 | 这套题过没过 | 通过率饱和后没有区分度；形态是考试 |

现在换成**能力画像**：按维度记录每个产品的表现（数值 + 方法 + 证据），再用同一套数据横向对比。

四个区，一条数据流：

```
维度区（看什么） → 场景区（做什么事） → 运行区（一个场景 × 多个产品） → 报告区（矩阵 + 导出）
```

维度页右侧仍保留「这个维度下的场景导航」，场景页是全局视图（按维度筛选、看采集状态）。

**场景是「做一件具体的事」**：修一个复杂 bug、从零做一个项目，常常还带多轮对话。设计场景时会尽量多照到几个维度，但不追求全覆盖——照不到的维度这次就是没有数据，这是正常的。

**执行单位是场景，对比单位是产品。** 一轮 = 一个场景 × 多个产品，一个产品一份 `run.json`，报告把同一场景下的产品并排。

## 2. 数据模型（JSON，无数据库）

### 维度

```json
{
  "id": "inline-completion",
  "name": "行内补全与生成",
  "note": "行内补全、函数级 / 文件级生成",
  "indicators": [
    { "key": "first_token_ms", "label": "首 token 延迟", "unit": "ms",
      "method": "script", "aggregate": "last" }
  ]
}
```

- `method`：`script`（脚本采集）/ `human`（人工记录）/ `llm`（模型评审）
- `aggregate`：`last` / `sum` / `avg` / `max` / `min`；稳定性、成本这类跨运行指标用 `sum` / `avg`

### 场景

```json
{
  "id": "full-delivery",
  "title": "综合场景：存量仓库跨模块改造",
  "kind": "command",
  "dimensions": ["inline-completion", "multi-file", "repo-context", "agent-autonomy",
                 "speed", "stability", "accuracy", "permission"],
  "brief": "读懂 → 计划 → 跨文件实现 → 被打断后追加需求 → 自测交付",
  "prompts": ["先别改代码，读仓库并给改动计划", "按计划实现并补测试", "停一下，再加一个边界情况", "自测到通过"],
  "command": { "argv": ["python3", "probes/full_delivery.py", "{prompts}"], "timeout_s": 3600, "cwd": "" }
}
```

- `prompts` 是多轮对话，一轮一条；采集器拿到的是 `{prompts}` 指向的 JSON 文件和 `WT_PROMPTS_FILE`
- 一个场景照不到全部维度是常态
- 默认只带 **一个综合场景**（`full-delivery`，4 轮，照到 8 个维度）；需要拆细时再在场景页加
- 仓库不单独配置：**写进第 1 轮提示词**（例如「把 https://github.com/… clone 到工作目录」），由产品自己拉取；场景只描述「做什么」

- `kind`：`command`（子进程自动采集，`method=script`，正常路径）/ `manual`（没有采集器时的**补录**，`method=human`，界面上只留一个小入口）
- `command.argv` 由操作者自己写；子进程 stdout 最后一行 JSON 里的键若与指标 `key` 同名，自动落成 measurement
  - 例：`{"first_token_ms": 1200, "files_changed": 5, "notes": "..."}`

### 运行（一次 = 产品 × 场景 × 重复）

`runs/survey/<run_id>/run.json`：

```json
{
  "run_id": "2026-10-30-161200-qoder-p1",
  "ts": "2026-10-30T16:12:00+08:00",
  "product": { "id": "qoder-ide", "name": "Qoder CN IDE", "family": "Qoder CN",
               "version": "0.4.9", "model": "..." },
  "scenario": { "id": "p1-inline-complete", "title": "P1 行内补全" },
  "dimensions": ["inline-completion", "speed"],
  "status": "ok",
  "method": "human",
  "confidence": "single",
  "duration_s": 300.0,
  "notes": "",
  "measurements": [
    { "dimension": "speed", "indicator": "first_token_ms", "value": 1200,
      "unit": "ms", "method": "human", "evidence": "" }
  ],
  "snapshot": { "scenario_hash": "a1b2c3d4", "dimension_defs": {} }
}
```

- `snapshot` 是「出生证明」：改了维度或场景也不用版本表，旧数据自带当时的定义和哈希
- `confidence`：`single`（一次观察）/ `repeat`（复现 2 次以上）/ `measured`（有脚本实测）

## 3. 覆盖核对（辅助，不是主流程）

主流程是「选场景 → 选产品 → 跑」，不需要凑维度。`coverage()` 只回答一个辅助问题：
**我想看的这几个维度，有没有场景能照到？** 它按贪心求一个最小集合，没被覆盖的列进 `uncovered`。

运行页会直接显示当前场景覆盖了哪几个维度、缺哪几个；缺的不影响这轮运行，只是那些维度这次没有数据。

## 4. 报告

- 矩阵：行 = 维度，列 = 产品（按 `id + 版本` 分组），格子里每个指标一行：值 + 单位 + 方法 + 次数
- 不可比就留空并说明（没跑、只有一次、版本不同）
- 导出 Markdown（复用 `report_share.py` 出 HTML / PDF 的路径）

## 5. 迁移映射

| 原能力 | 现在的位置 |
|---|---|
| 走查的 launch / shot / click / cdp | 场景 `command` 的可调用工具 |
| 走查的事件日志、截图配对 | 场景产出放 `runs/survey/<run>/`，measurement 带 `evidence` |
| 走查的严重度 / 置信度 | 收敛成 `confidence` 与报告的「方法」标记 |
| 评测的 `grade.py` / 隐藏验收 | 「效果 / 准确度」维度的脚本判据 |
| 评测的 `scorecard` / `timing` | 报告矩阵的素材 |
| 评测的通过率 / 任务档位 | 删除（考试框架的产物） |
| `selftest` / `check_tasks` | 保留：采集器自己要先被证伪 |

## 6. 不做

- 数据库、ORM、迁移脚本
- 维度版本表（用 run 里的 `snapshot` 代替）
- JSON schema 校验（报告层容忍缺失字段）
- 一次性合成大报告（每批跑完就能看矩阵）
- 把 n=1 的观察写成成功率

## 6.5 执行器（内部，不出现在界面上）

「开始自动体验」背后是 `workbench/executor.py`：它按产品的适配器把场景的多轮提示词发进去，
统一采集耗时、首 token、工具调用步数、token 用量、失败轮次、改动文件，写成和命令路径一样的
`run.json`。

- 适配器只负责「怎么发一轮、什么时候算这一轮结束」；指标由共享的 runner 采集
- 当前有 Codex CLI 适配器（`codex exec --json` / `resume --last`）；GUI 产品的 CDP 适配器还没写
- 没有适配器的产品，按钮会拒绝并给一句人话，不解释内部结构

## 7. 接口

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/survey` | 维度、场景、覆盖数、最近运行 |
| POST | `/api/survey/dimension/save` | 新增 / 修改维度 |
| POST | `/api/survey/dimension/delete` | 删除维度（同时从场景里摘掉） |
| POST | `/api/survey/scenario/save` | 新增 / 修改场景 |
| POST | `/api/survey/scenario/delete` | 删除场景 |
| POST | `/api/survey/plan` | 维度 → 场景覆盖核对（辅助） |
| POST | `/api/survey/run` | 单产品跑一个 `command` 场景 |
| POST | `/api/survey/batch` | 一个场景 × 多个产品，顺序跑（主路径） |
| POST | `/api/survey/record` | 写一条人工记录 |
| GET | `/api/survey/report` | 矩阵数据 |
| POST | `/api/survey/export` | 导出 Markdown |

维度 / 场景配置存在 `~/.config/tool-walkthrough/survey.json`（可用 `WT_SURVEY` 覆盖），运行数据在 `runs/survey/`。
