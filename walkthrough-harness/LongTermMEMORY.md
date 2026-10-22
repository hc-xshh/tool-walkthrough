# Long-Term Memory — Walkthrough Lessons

> Format: cue → lesson → evidence → confidence, one or two lines each. Only lessons not already in `METHOD.md`. Append 1–3 per run; never paste logs.
> Product names are anonymised in this distributed copy: "client A" = a reviewed Electron client, "client B" = another one.

- **cue**: permission dialog with "always allow for this session" → **lesson**: keep operating after choosing it; if the same prompt returns, that is a finding—screenshot both times. **evidence**: client A deep research, ≥3 prompts in one task. **confidence**: medium-high.
- **cue**: using the tool's own research output as evidence → **lesson**: run the same capability twice; one wrong + one right means unstable, not fixed. **evidence**: two reports on the same product contradicted each other on platform support. **confidence**: high.
- **cue**: evaluating first-run experience → **lesson**: re-check the home screen after login; promos or credit offers may only appear then, so the login page is not the first-run impression. **evidence**: client A login page clean, post-login home had two credit promos. **confidence**: high.
- **cue**: driving a windowed app through CDP → **lesson**: take the screenshot with `wt.py shot` right after every click, not with a separate window-capture helper; `audit` pairs clicks with shots inside a 5-event window, and a helper bypasses the event log, so the run ends with avoidable `click -> shot` WARNs. **evidence**: TRAE CN run 2026-10-22, 3 unpaired CDP clicks. **confidence**: high.
