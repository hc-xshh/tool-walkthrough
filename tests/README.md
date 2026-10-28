# Tests

检查项自己的回归测试。标准库 `unittest`，不需要装任何东西：

```bash
python -m unittest discover -s tests -v     # 84 个用例，约 5 秒
python -m pytest tests -q                   # 装了 pytest 也能跑
```

## 为什么用 unittest 而不是 pytest

方法包的前提是"装完就能跑"——`harness/requirements.txt` 里只有 4 个运行期依赖，
不该为了让工具自测再多一个开发依赖。pytest 能直接收集 `unittest.TestCase`，
两种都行。

## 测什么

`support.py` 提供 `make_run()`：在临时目录里拼一个"看起来像真 run"的目录
（`ui-map.md`、`task-plan.md`、`report.md`、`screens/*.png`、`harness.json`），
每个用例只改一处，再断言 `coverage` / `audit` 的反应。

| 文件 | 覆盖 |
|---|---|
| `test_coverage.py` | 首访图、每屏有任务、S 编号、导航边数与目标、一级入口（含"只写不测不算"）、状态矩阵（缺失 / 少于三行 / 三行默认 / 没到没原因）、单屏与空地图不崩 |
| `test_audit.py` | 模板占位符不算幻觉引用、真缺图判 FAIL、事件指向已删图判 FAIL、error 事件只 WARN、任务数 8–15（空结果不算）、问题缺归因/置信度判 WARN、缺「问题总览」判 WARN、`--strict` 把 WARN 变失败 |
| `test_cli.py` | 各子命令 `--help` 都能起、`coverage` / `audit` / `evidence` 的退出码与提示语 |
| `test_launch_env.py` | `ELECTRON_RUN_AS_NODE` 从子进程环境剥离，且不修改调用方字典 |
| `test_evidence.py` | PNG IHDR 尺寸、`evidence.json` 证据类型匹配、低分辨率判 `low-res`、空文件判 `no-shot` |
| `test_preflight.py` | Cursor 额度、Qoder 账号/模型限制的阻断标记；正常文本不误报 |
| `test_cdp_pick.py` | 多 target 时选主页面：`desktop-pet` 排在 `renderer` 前、空页、`--match` 强制指定 |
| `test_xlsx_audit.py` | 图片跨格复用、超出单元格、行高 >409.5pt、缺失证据标注、状态冲突 |
| `test_report_images.py` | 涂白改写像素（界内变白、界外不动、越界不崩、JPEG 源输出 PNG）、`redact` 的 `*` 通配与按图合并、本地图内联为 data URI（远程/缺失/未知扩展名不动）、图注编号（起点续号、alt 转义、alt 含 `>` 仍能编号）、`--redact` 参数格式错误退 2 |

## 加用例的原则

1. **一条用例一个判据**：名字说明"什么应当被拒/被接受"，不要在一个用例里堆三个断言。
2. **负例优先**：这些检查的价值在于"拦住偷懒"，所以先写"这样写应该被拦"。
3. **回归要有出处**：修过的 bug 用注释标明现象（例：`UnboundLocalError regression`，
   单屏产品会让 `coverage` 直接崩）。
4. **不碰真 run**：所有用例都在 `tempfile.TemporaryDirectory()` 里造数据，
   `runs/` 下的真实记录只用于人工复核。
