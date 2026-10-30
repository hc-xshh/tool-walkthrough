# TODO

## 已完成

- [x] **网络搜索配置**：配置页可选 DeepSeek / Exa / Tavily / Brave / Perplexity，key 只写不读，支持 Base URL、结果数、保存并测试。
- [x] **DeepSeek Search API**：走 `/v1/tools/search`（与 DSH 的 `deepseek-search-api` 一致），一次直接搜索，不走 Messages 轮次；解析结构化 `results[]`，不从回复文本抓 URL。
- [x] **DeepSeek 复用模型 key**：模型也是 DeepSeek 时，搜索默认复用模型 key；也可以单独填一个搜索 key 覆盖。其他 provider 必须单独配置 key。
- [x] **固定产品谱系**：`catalog/*.json` 一个家族一个文件，前端只读展示公司、定位、产品线、可测面、来源和核实时间。
- [x] **自定义应用 / 驱动器**：本地 `plugins.json`，支持添加应用、设置路径、注册驱动器、移除/恢复默认。
- [x] **接入页主操作区去掉手工新增/注册**：已收进页面底部的「高级 / 手工补充（过渡）」，正式版删除。
- [x] **一句话加产品**：输入「加上 Kimi Work」→ 固定谱系匹配 / 网络搜索 / LLM 整理产品信息 → 本机安装探测 → 产品卡；有 job 进度和日志。
- [x] **自动发现产品卡**：显示厂商、定位、形态、来源、本机安装状态；找到 GUI 连接时可启动应用、开始走查；未安装时给官网和“安装后重新查找”。
- [x] **本地探测（Linux/.desktop + PATH，macOS /Applications）**：不自动下载、不自动安装、不自动启动。

## 用户要做

- [ ] 如果用 **Exa / Tavily / Brave / Perplexity**：在 **配置 → 网络搜索** 选择服务商，填对应搜索 key，点「保存并测试」。
- [ ] 如果模型也是 **DeepSeek**：默认已复用模型 key，可以不改；要单独 key 时直接填在搜索卡片里。
- [ ] 用「保存并测试」搜一次 `DeepSeek`，确认 provider 返回结果；测试会消耗一次额度。

## 接入（继续完善）

- [ ] 失败恢复再细化：需登录暂停等待；有安装但没 CDP 时提示桌面后端；重试保留上次 query。
- [ ] 本地探测补 Windows / 更多 macOS 安装形态。
- [ ] 未收录产品的本地 overlay 已有；补“维护者提升为正式 catalog”的导出/审核流程。
- [ ] 产品卡直接放「开始评测」：等通用/专用 driver；现在只能开始走查。
- [ ] 一句话流程稳定后，删除「高级 / 手工补充」入口。

## 通用 driver（下一步）

- [ ] 通用 CLI driver：命令模板 + prompt + timeout + workspace diff + smoke test。
- [ ] 通用 GUI driver：CDP 找输入框/等待空闲；先标 experimental。
- [ ] 专用 driver 与通用 driver 的可靠性标签；不要混在一起展示。

## 维度 · 运行 · 报告

- [x] 维度 CRUD：名称 / 指标 / 单位 / 采集方式（脚本 / 人 / LLM）/ 聚合方式。
- [x] 场景 CRUD + 维度下的场景导航（场景是全局对象，被多个维度共享）。
- [x] 选维度求最小场景集，运行落 `runs/survey/<run_id>/run.json`（含定义快照）。
- [x] 报告：维度 × 产品矩阵、逐格明细、导出 Markdown。
- [ ] 命令采集的探针脚本：行内补全（CDP 打字 + 首 token）、危险操作的确认框计数。
- [ ] 报告接 `report_share.py` 出 PDF / 钉钉单文件。
- [ ] 场景模板与 `templates/task-plan.md` 打通，支持导入。
- [ ] 旧评测线（code-eval 驱动器）只作为「效果」维度的判据保留，不再占界面入口。

## 产品谱系

- [ ] 补 WorkBuddy、Kimi、ZCode 等家族；每个家族一个 JSON，带来源和 `verified_at`。
- [ ] 产品线变化时更新 catalog；自动发现结果不直接改仓库文件。

## 验收

- [ ] 配置 DeepSeek 后「保存并测试」能返回至少一条结果。
- [ ] `catalog/*.json` 加一个 WorkBuddy 文件后，前端不用改代码就能展示。
- [ ] 一句话接入一个未收录产品，完成后产品卡能直接开始走查。
- [ ] 通用 CLI driver 在一个真实 CLI 上跑通一个 code-eval 任务。
