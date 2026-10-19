# Guardrails

- **Credentials are user-only.** Never type passwords, API keys, 2FA codes, or scan codes. Never accept them in chat.
- **Never touch the real desktop or real app config.** Use Xvfb + isolated HOME. The only exception is reusing a login state the user already created, with the real HOME.
- **No destructive actions on user data.** No payments, no connector authorization, no deleting real projects.
- **Do not fix the product mid-run.** A blocked step is a finding; log it and continue.
- **Do not present the product's own output as the walkthrough report.** Tool-generated reports go to `artifacts/` and are labeled "被测产物".
- **Do not call it a product defect until the environment is excluded.** Check display, DBus, fonts, proxy, permissions, and version first.
- **S3/S4 stay unverified until a human reviews.** Mark them explicitly.
- **Do not write a competitor comparison report.** The deliverable is an observation of the tool under test.
- **Timebox research.** 20–30 minutes; write "not found" instead of guessing.
