# Guardrails

- **Credentials are user-only.** Never type passwords, API keys, 2FA codes, or scan codes. Never accept them in chat.
- **Environment: real desktop only.** The harness no longer supports Xvfb or any virtual display. Run on the real session (`DISPLAY=:0`, `--profile linux-desktop`); virtual-environment findings are not valid product findings. Keep the run read-only: no installs, deletes, or config edits.
- **Never change the real app config.** Even in tier 3, do settings changes in a copy or the isolated HOME.
- **Reusing an existing login state (exception).** Only the user's own account, in this order:
  1. Confirm the account is already logged in on the real desktop; never re-enter credentials.
  2. Use the real desktop and the already logged-in profile; do not point the harness at a private HOME or a dummy DBus.
  3. Check the single-instance lock before launching a second copy; never type credentials into the harness.
- **No destructive actions on user data.** No payments, no connector authorization, no deleting real projects.
- **Crawling stops at the dialog, not at the click.** While walking the product (METHOD Step 1), a control that would install a plugin, download a package, start a paid run, or delete something may be *opened* but not *confirmed*: stop at the dialog, screenshot it, write "未展开" plus the reason, and go back. "The crawl needed it" is never a reason to click through.
- **Payments and connector authorization are not tested.** When a task needs a charge or a connector auth, mark the task `Not tested`, write the reason into the report's boundary list (`METHOD.md` §10, under method & limits), and continue with the other tasks. A blocked paid/authorized step must not stall the run.
- **Evidence and PII stay local.** `runs/` and machine logs are not committed by default. For a public repo, run `bash harness/install-git-hooks.sh` once, then put your handle, email, and local username into `.git/pii-terms` (the hooks read it). Never `git add -f runs/`. Redact screenshots and traces before any commit.
- **Redact before the PDF leaves the machine.** Account handles, phone numbers, payment QR codes and tokens must be painted white in the deliverable (`wt.py report --redact`, or the `redact` key in `captions.json`); a white CSS block is not enough, it has to be pixels. Keep the unredacted originals only under `runs/`.
- **Do not fix the product mid-run.** A blocked step is a finding; log it and continue.
- **Do not present the product's own output as the walkthrough report.** Tool-generated reports go to `artifacts/` and are labeled "被测产物".
- **Do not call it a product defect until the environment is excluded.** Check display, DBus, fonts, proxy, permissions, and version first; attribute every finding (product / script / environment / undecided) and say how many times it reproduced. A click that missed is not a defect.
- **S3/S4 stay unverified until a human reviews.** Mark them explicitly.
- **Do not claim full coverage.** A crawl covers the screens you can reach while the product sits still; write "N screens, M states", never "everything".
- **S3/S4 stay unverified until a human reviews.** Mark them explicitly.
- **Do not write a competitor comparison report.** The deliverable is an observation of the tool under test.
- **Timebox research.** 20–30 minutes; write "not found" instead of guessing.
