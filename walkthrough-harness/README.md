# Walkthrough Harness（借 Harness² 的组件模型）

这不是 Google Harness² 的复刻，只借它两件事：**8 个可编辑组件** + **任务级 / 改进级两层循环**。我们的任务不是让 agent 刷 benchmark，而是让「走查」这件事每跑一次更稳一点。

## 组件映射

| Harness² 组件 | 这里放什么 |
|---|---|
| system prompt | `systemprompt.md`：执行顺序、决策契约、六件交付物、完成判据 |
| guardrails | `guardrails.md`：凭据只由用户输入、环境三档、PII 与证据入库规则 |
| memory | `LongTermMEMORY.md`：跨轮经验（cue / lesson / evidence / confidence） |
| tool guidance | `tool_descriptions/tool_guidance.md`：工具怎么调（cdp.py 读取 / 点击 / 输入、平台接线） |
| skills | `skills/README.md`：四类；`skills/finding-writing/SKILL.md` 可直接照做 |
| subagents | `sub_agents/README.md`：盲评（可选）、证据审计（发现定稿前必做） |
| scripts | `scripts/README.md`：preflight、desktop、cdp、build-report |
| plugins | `plugins/README.md`：预留（reserved），当前不参与流程 |

## 两层循环怎么跑

**任务级（每次走查）**
1. 选 1–3 个候选改动（来自上一轮经验，例如「加连续任务」「权限弹窗截两张」）
2. 只在一个便宜任务上试跑（不跑全量）
3. 看证据：有没有多抓到真问题、有没有引入误报
4. 保留有证据的改动，写进 METHOD / 模板

**改进级（跨次）**
1. 每次收尾往 `LongTermMEMORY.md` 追加 1–3 条
2. 只写可复用的 cue，不写流水账
3. 下轮开始先读它，再设计任务

## 我们故意不做的

- 不让 LLM 自动改自己的 prompt 去「优化分数」：没有可信 rubric 时，只会对着噪声优化
- 不跑厂商自定义的 benchmark：它是任务完成度评测，不是体验走查；且可能带自定义许可
- 不把组件数量当质量：一个组件只有在能降低走查出错率时才留
