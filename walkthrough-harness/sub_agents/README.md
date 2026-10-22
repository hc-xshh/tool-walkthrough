# Subagents

Two roles. Rater B is optional calibration; the evidence auditor is required before findings are finalized. This package ships the prompts only—it does not wire up subagent runtime; without subagents, the main evaluator runs the same prompt as a self-audit and records the result in the report.

## Rater B (blind severity)

Prompt:

> You are a second usability rater. You receive the task matrix, screenshots, and raw finding text, but **not** the first rater's severity scores. Score each finding 0–4 using METHOD §4. Return a table: finding ID | score | one-line reason. Do not rewrite the findings.

Use: compare with Rater A; a gap ≥2 means the finding is ambiguous—rewrite it before shipping. Record both scores in `harness.json` as `raters`.

## Evidence auditor

Prompt:

> For each finding, open the cited screenshot/log path. Check that the evidence shows the claimed element and consequence. Return: finding ID | evidence exists (yes/no) | claim matches (yes/partial/no) | note.

Use: required before the report is finalized. Any "no" blocks the finding until fixed or marked `未核实`.
