# Eval Console（只读评测控制台）

给评测人员看的本地页面：任务目录、运行列表、逐条结果、工具 × 任务对比。
**只读**：不启动评测、不写 `runs/`、不连外部服务。

## 生成

```bash
cd ~/workspace/tool-walkthrough
python3 code-eval/tools/build_dashboard.py
# 默认输出 runs/dashboard/；也可以：
python3 code-eval/tools/build_dashboard.py --runs runs --out runs/dashboard
```

生成四件东西：

- `index.html` / `styles.css` / `app.js`：页面模板，来自本目录
- `data.js`：从 `runs/*/results/*.json` 和 `code-eval/tasks/*.json` 生成的快照

`data.js` 是生成物，跟着 `runs/` 一起被 gitignore；不要手改。

## 打开

```bash
cd runs/dashboard
python3 -m http.server 8787
# 浏览器打开 http://127.0.0.1:8787/
```

直接双击 `index.html` 也可以，`data.js` 是本地脚本，不依赖 fetch。
建议用本地 HTTP，方便后续把截图/报告链接接进来；不要把 `runs/` 直接暴露到公网。

## 页面

| 路由 | 内容 |
|---|---|
| `#/overview` | 任务数、运行数、通过率、中位耗时、最近运行/结果、任务分布 |
| `#/tasks` | 任务目录，按分类/难度/搜索筛选 |
| `#/tasks/<id>` | 题面、需求映射、历史尝试 |
| `#/runs` | 运行列表 |
| `#/runs/<id>` | 一次运行的全部结果 |
| `#/results/<run>/<task>/<rep>` | verdict、需求、隐藏验收、scope/quality/claims、diff |
| `#/compare` | 工具 × 任务通过矩阵 |

## 设计约束

- 不引第三方前端依赖，不打包，不需要 Node（Node 只用于被测任务的 L12）。
- 所有动态文本走 `esc()`，不把 JSON 当 HTML 插入。
- 结果 schema 变了，先改 `build_dashboard.py` 的 `compact_result()`，再改 `app.js`；不要把整份 result JSON 直接塞进页面。
- `runs/` 里可能有截图、日志和绝对路径，页面默认只展示摘要，不展示 stdout/stderr。
