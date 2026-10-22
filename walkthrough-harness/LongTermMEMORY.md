# Long-Term Memory — Walkthrough Lessons

> Format: cue → lesson → evidence → confidence, one or two lines each. Only lessons not already in `METHOD.md`. Append 1–3 per run; never paste logs.
> Product names are anonymised in this distributed copy: "client A" = a reviewed Electron client, "client B" = another one.

- **cue**: permission dialog with "always allow for this session" → **lesson**: keep operating after choosing it; if the same prompt returns, that is a finding—screenshot both times. **evidence**: client A deep research, ≥3 prompts in one task. **confidence**: medium-high.
- **cue**: using the tool's own research output as evidence → **lesson**: run the same capability twice; one wrong + one right means unstable, not fixed. **evidence**: two reports on the same product contradicted each other on platform support. **confidence**: high.
- **cue**: evaluating first-run experience → **lesson**: re-check the home screen after login; promos or credit offers may only appear then, so the login page is not the first-run impression. **evidence**: client A login page clean, post-login home had two credit promos. **confidence**: high.
- **cue**: driving a windowed app through CDP → **lesson**: let the harness own the screenshots — `wt.py click` shoots right after the click and `cdp.py ... --capture` does the same; a separate window-capture helper bypasses `events.jsonl` and leaves `click -> shot` WARNs. **evidence**: TRAE CN run 2026-10-22, 3 unpaired CDP clicks, fixed in the same run by adding click-time capture. **confidence**: high.
- **cue**: shipping a report PDF → **lesson**: check the appendix before sending; every PNG in `shots/` is embedded by default, so exclude receipts/QR codes (`--exclude`, or `"exclude"` in `captions.json`) and give captions, otherwise the PDF carries unredacted screens while the text claims it is redacted. **evidence**: TRAE CN 2026-10-22, payment QR reached the PDF while the report said it was excluded. **confidence**: high.
