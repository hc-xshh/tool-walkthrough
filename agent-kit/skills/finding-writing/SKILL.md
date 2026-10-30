---
name: finding-writing
description: Turn one walkthrough observation into a scored, evidence-backed finding and file it into report.md. Use after a task deviates from the expected path, before scoring or sorting anything.
---

# Finding writing

Use this at METHOD Step 4/5: write the finding first, then score it.

## Inputs

- Task ID and the step where it deviated.
- At least one screenshot or log that shows the element and the consequence.
- `../docs/METHOD.md` §4 (severity) and §5 (finding formula).

## Steps

1. Write the observation as **element + consequence**, with no number yet: "首屏同时弹出两个积分活动，主输入框被夹在中间".
2. Attach evidence: exact `shots/...` or `logs/...` path. No evidence → write `未核实`; do not score.
3. Write the impact: who hits it, under what condition, main path or edge.
4. Write the **minimum reproduction**: numbered steps from a known start state; a reader must be able to replay it without asking.
5. Write the recommendation as an action a designer can start: "首启只保留一个可关闭提示".
6. Run the three counter-checks from METHOD Step 4: is it the environment? is it an inference? is it a duplicate?
7. Only then assign 0–4 per METHOD §4; flag S3/S4 for human review, and single-rater scores as `未校准`.
8. Set **置信度** (`已复核` / `单次` / `推断`). Inference never gets promoted to a conclusion in the report.
9. Append to `report.md` §4 with all four fields (归因 / 复现 / 置信度 / 最小复现). S1/S2 go into the §4 table — **the table keeps 影响面、最小复现、置信度 columns**, it is not a one-line dump.
10. Re-read once: would the designer need a meeting to understand it? If yes, rewrite.

## Self-check

- [ ] The exact screen element is named.
- [ ] The consequence is what the user did next, not "confusing".
- [ ] The evidence path exists inside the run directory.
- [ ] **影响面** says who hits it and whether it is a main path or an edge.
- [ ] **最小复现** is numbered steps a stranger can replay.
- [ ] **置信度** is set; 推断 is not written as fact.
- [ ] No "user couldn't find it" phrasing.
- [ ] Severity has a reason; S3/S4 flagged for review.
- [ ] Not a duplicate; merged into the existing ID if it was.

## Example

Weak: "登录页体验不好."

Strong: "登录页只有一个「登录」按钮，没写支持哪些账号类型；用户无法判断该用微信、手机号还是企业账号。证据：`shots/t02-03-login.png`。建议：按钮下补一行登录方式。S2。"
