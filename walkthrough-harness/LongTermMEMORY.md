# Long-Term Memory — Walkthrough Lessons

> Format: cue → lesson → evidence → confidence. Append 1–3 per run. Do not paste logs.
> Product names are anonymised in this distributed copy: "client A" = a reviewed Electron client, "client B" = another one.

## L1 Electron desktop: try CDP before OCR
- **cue**: desktop app is Electron / WebView
- **lesson**: read DOM and click by label through `--remote-debugging-port`; OCR only for native dialogs, file pickers, tray
- **evidence**: two Electron clients: DOM text matched screenshots; label clicks worked after `suppress_origin=True`
- **confidence**: high

## L2 Ubuntu deb: check chrome-sandbox mode before first launch
- **cue**: installing an Electron `.deb` on Ubuntu
- **lesson**: `chrome-sandbox` should be `root:root 4755`. If it is 755, launch may fail FATAL — but the same mode can still launch another app, so test the app instead of inferring from the mode
- **evidence**: client A 5.x deb failed FATAL at 755 (workaround `--no-sandbox`); another client launched at 755 on the same host
- **confidence**: high

## L3 After a completed task, try a second task
- **cue**: task-based agent client
- **lesson**: send a second task immediately after the first completes; a dead composer/send button is a state bug, not a script bug
- **evidence**: client A 5.x, reproduced twice; restart restored sending
- **confidence**: high for this version

## L4 "Always allow" may not persist
- **cue**: permission dialog with "always allow for this session"
- **lesson**: keep operating after choosing it; if the same prompt returns, that is a finding; screenshot both the first and the repeat
- **evidence**: client A deep research, at least 3 prompts in one task
- **confidence**: medium-high

## L5 Numbered option dialogs need index clicks
- **cue**: permission option text looks like `1\n允许读取`
- **lesson**: exact-text clicking fails; use `cdp.py clickel 允许读取 --nth 0` or click `[class*=optionItem]` by index
- **evidence**: client A permission prompt, first attempt missed
- **confidence**: high

## L6 Official docs can omit the real download channel
- **cue**: official site says "download from the app store"
- **lesson**: also probe the update API and package metadata; "not on the website" does not mean "does not exist"
- **evidence**: client A official site vs. its vendor update endpoint, which served a Linux deb
- **confidence**: high

## L7 Research accuracy varies across runs
- **cue**: using the tool's own research output as evidence
- **lesson**: run the same capability twice; compare artifacts; one wrong + one right = unstable, not fixed
- **evidence**: two reports on the same product gave opposite statements about platform support
- **confidence**: high

## L8 Fresh HOME and real HOME show different first screens
- **cue**: evaluating first-run experience
- **lesson**: install/login page uses a fresh HOME; after login, switch to the real HOME. Promos may only appear after login
- **evidence**: client A login page clean; post-login home had two credit promos
- **confidence**: high
