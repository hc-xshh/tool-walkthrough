# Skills

Four skills carry the walkthrough. They live in `METHOD.md` and `templates/`; this file is the index.

## 1. Tool research (Step 0)

- Read official docs/pricing/changelog/status first; do not rehearse the UI.
- Fill `templates/tool-profile.md`: facts + claims table (claim / source / date / verification / result).
- Timebox 20–30 minutes; "not found" is a valid result.

## 2. Task plan

- 5–8 user tasks: first run, core task, artifact retrieval, failure state, settings, **continuous task**.
- Each task: start state, success criterion, observation points.
- Use `templates/task-plan.md`.

## 3. Finding writing

- element + consequence + evidence + 0–4 + recommendation.
- No "user couldn't find it"; describe the path taken.
- Mark inference vs fact; S3/S4 need human review.

## 4. Report

- Six sections: summary → task matrix → findings → what worked → method & limits → appendix.
- Use `templates/report.md`; build PDF with `harness/build-report.py`.
- The product's own output is evidence, not the report.
