# office-eval — 办公产物的判分（实验）

判分的是 **agent 交出的文件**：xlsx 里的数、docx 里的结构。和 `code-eval` 同一套思路
（隐藏验收在产物之外、判分只看结果），只是验收器换成 openpyxl / python-docx。

## 目录

```
office-eval/
  tasks/        任务规格（fixture / accept / prompt / 允许写的目录）
  fixtures/     数据包（只读的 data/ + spec.md）
  accept/       隐藏验收：读产物、按 spec 断言
  solutions/    参考产物（带错误变体，用来验证判分口径）
  tools/        grade.py（判分）+ selftest.py（口径自测）
```

## 跑一次

```bash
# 1. 复制数据包到工作目录
cp -r office-eval/fixtures/O1-xlsx-quarterly/repo runs/<run>/work/O1-r1

# 2. 让被测工具按 spec.md 生成 out/quarterly.xlsx

# 3. 判分（--python 要指向装了 openpyxl 的解释器）
python office-eval/tools/grade.py --task O1-xlsx-quarterly \
    --workdir runs/<run>/work/O1-r1 \
    --out runs/<run>/results/O1-r1.json \
    --python "$OFFICE_PYTHON"

# 4. 口径自测（不需要被测工具）
python office-eval/tools/selftest.py     # 5 个用例：正确产物 + 3 个错误变体 + 空产物
```

`OFFICE_PYTHON` 需要能 `import openpyxl`（docx 任务再加 `python-docx`）。DSH 自带的运行时
两者都有；系统 Python 一般没有。

## O1 考什么

按 `spec.md` 从 `data/sales.csv` 生成 `out/quarterly.xlsx`：

- 两个工作表（`Q1` / `明细`），名字和表头顺序固定
- 月度销售额 = Σ units × price × (1 − discount)，2 位小数
- 环比存小数、单元格格式 `%`、保留 1 位、首月写 `—`
- `Q1` 末行合计：6 单 / 4842.00

隐藏验收 9 条，覆盖：sheet 名、表头、订单数、销售额、环比值与格式、合计行、明细行序、
明细金额之和。改 `data/` 或 `spec.md` 判 `scope_violation`。

## 加一个任务

1. `fixtures/<id>/repo/`：只读数据 + `spec.md`（规格就是验收标准，写清楚列名/顺序/口径）
2. `accept/<id>/test_accept.py`：用 openpyxl / python-docx 读产物断言；不要读 agent 的中间文件
3. `tasks/<id>.json`：`fixture` / `accept` / `prompt` / `allowed` / `forbidden` / `timebox_s`
4. `solutions/`：加一个参考产物 + 至少一个错误变体
5. `tools/selftest.py` 里加 `(variant, expect)` 两条

## 边界

- 目前只有 xlsx 一个任务；docx（标题层级、表格、占位符残留）是同样形状的第二个
- 还没在真正的办公 agent（WorkBuddy 那类）上跑过，只在参考产物和错误变体上验证过判分口径
- 样式类要求（字体、字号、行高）不进验收：主观且容易误判，交给体验走查那一半
