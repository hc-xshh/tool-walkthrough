# Product catalog

只读产品谱系。一个家族一个 JSON 文件；前端只展示这里的数据，用户不编辑家族/产品。

## 加一个家族

1. 新建 `catalog/<family-id>.json`，按 `qoder-cn.json` 的结构填：
   - `id` / `name` / `vendor` / `positioning`
   - `aliases` / `category` / `homepage` / `docs`
   - `sources`：至少一条官网或官方文档，写 `verified_at`
   - `products[]`：`id` / `name` / `form` / `surfaces[]`
2. `surfaces[]` 是真正被测的面：
   - `app_id` 可选，指向 `workbench/apps.py` 的内置 app；
   - `driver_id` 可选，指向 `code-eval/drivers.json` 的 driver；
   - 两者都没有就是「已收录，未接入」。
3. 跑 `python3 -m unittest tests.test_catalog`，再刷工作台。

`form`：`ide` / `cli` / `work` / `plugin` / `cloud` / `desktop` / `agent` / `web`。  
`kind`：`gui` / `cli` / `plugin` / `cloud` / `desktop` / `agent` / `web`。

## 边界

- 不写可执行文件路径、端口、key；这些属于本机连接（`plugins.json`）。
- 一个坏文件不会拖垮整页：加载器会跳过并显示错误。
- 新增家族只加数据文件，不改前端、不改 Python 枚举。
