# Tool Guidance

Method content is not repeated here: evidence rules and before/after pairing live in `METHOD.md` §8; environment tiers in `guardrails.md`; install verification, CDP-first order and OCR fallback in `METHOD.md` §9. What follows is only how to call the tools.

## Read the UI

- Electron/WebView: `cdp.py --port <p> text` for visible text; `eval` for DOM structure.
- Scope dialogs first: `document.querySelector('.wb-modal, [role=dialog]')`, then query inputs inside it. Background pages may have their own composer.

## Click

- Prefer label clicks: `cdp.py clickel "新建任务"`.
- React handlers sometimes ignore DOM `.click()`; `clickel` sends real mouse events.
- Numbered options: `cdp.py clickel "允许读取" --nth 0` (0-based, default is the last match).
- If a click returns but nothing changes, check state—not the return value.

## Type

- `contenteditable`: focus, then `Input.insertText`. If validation still says empty, send a space + backspace to trigger the editor's input handler, or blur the field.

## Know when a task actually finished

- Composer cleared + task list count increased = sent.
- "Stop" button gone + result card / artifact = finished.
- `aria-disabled=false` does not prove the button works.

## Environment

- macOS: Screen Recording + Accessibility for the terminal/agent.
- Windows: run in an interactive desktop session; session 0 cannot capture.
- Linux: `wt.py launch` / `app-launch.sh` set `WALKTHROUGH_HOME`, `WALKTHROUGH_DBUS`, `WALKTHROUGH_BASE`; display comes from the profile.
