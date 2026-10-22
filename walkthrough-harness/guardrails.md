# Guardrails

- **Credentials are user-only.** Never type passwords, API keys, 2FA codes, or scan codes. Never accept them in chat.
- **Pick an environment tier before launch.** Isolation is the default; the real desktop is a registered exception.
  1. **Default: isolated.** A separate OS user or VM, plus a private HOME (Linux: `WALKTHROUGH_HOME`). Use it for installs, logins, and config changes.
  2. **Linux headless / CI:** Xvfb + private DBus + `--profile linux-x11`; no native dialogs, and no conclusions about performance or motion.
  3. **Full look-and-feel walkthrough:** must use the real desktop session (`DISPLAY=:0`, `--profile linux-desktop`). Register the exception in the report's method & limits (why the real desktop, what was touched), and keep it read-only: no installs, deletes, or config edits.
- **Never change the real app config.** Even in tier 3, do settings changes in a copy or the isolated HOME.
- **Reusing an existing login state (exception).** Only the user's own account, in this order:
  1. Confirm the account is already logged in on the real desktop; never re-enter credentials.
  2. Point the run at that HOME / config dir: Linux `WALKTHROUGH_HOME=<real HOME>`, `WALKTHROUGH_DBUS=<real session bus>`; macOS / Windows use the real profile dir.
  3. Check the single-instance lock, close the running instance before launching on the isolated desktop, and relaunch it afterwards.
- **No destructive actions on user data.** No payments, no connector authorization, no deleting real projects.
- **Payments and connector authorization are not tested.** When a task needs a charge or a connector auth, mark the task `Not tested`, write the reason into the report's boundary list (`METHOD.md` §10, under method & limits), and continue with the other tasks. A blocked paid/authorized step must not stall the run.
- **Evidence and PII stay local.** `runs/` and machine logs are not committed by default. For a public repo, run `bash harness/install-git-hooks.sh` once, then put your handle, email, and local username into `.git/pii-terms` (the hooks read it). Never `git add -f runs/`. Redact screenshots and traces before any commit.
- **Do not fix the product mid-run.** A blocked step is a finding; log it and continue.
- **Do not present the product's own output as the walkthrough report.** Tool-generated reports go to `artifacts/` and are labeled "被测产物".
- **Do not call it a product defect until the environment is excluded.** Check display, DBus, fonts, proxy, permissions, and version first.
- **S3/S4 stay unverified until a human reviews.** Mark them explicitly.
- **Do not write a competitor comparison report.** The deliverable is an observation of the tool under test.
- **Timebox research.** 20–30 minutes; write "not found" instead of guessing.
