# Tool Guidance

## Read the UI

- Electron/WebView: `cdp.py --port <p> text` for visible text; `eval` for DOM structure.
- Scope dialogs first: `document.querySelector('.wb-modal, [role=dialog]')`, then query inputs inside it. Background pages may have their own composer.
- Native-only surfaces (file picker, tray, OS dialog): screenshot + OCR fallback.

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

## Evidence

- Screenshot before and after every state change.
- For permission dialogs: one shot at first appearance, one after "always allow" if it repeats.
- Keep raw logs; don't rewrite them.

## Environment

- Linux: launch Electron on Xvfb with `DISPLAY=:98`, `GDK_BACKEND=x11`, software rendering.
- macOS / Windows: no Xvfb; use `wt.py launch|shot|click` and isolate with a separate user account or VM.
- Same HOME / same account = single-instance lock; close the real-desktop instance first.
- After a completed task, try a second task before declaring the run done.
- macOS needs Screen Recording + Accessibility for the terminal/agent; Windows needs an interactive desktop session.
