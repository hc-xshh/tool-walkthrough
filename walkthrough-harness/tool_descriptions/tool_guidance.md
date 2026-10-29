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
- Windows: if an Electron app exits at once with code 9 (or `--version` prints a Node version), the host exported `ELECTRON_RUN_AS_NODE`; `wt.py launch` strips it, and `preflight` warns. Unset it yourself when launching by hand.
- Windows: write helper `.ps1` files as UTF-8 **with BOM**; PowerShell 5.1 reads BOM-less files as ANSI and Chinese window titles break at parse time.
- Native folder pickers: `harness/pick-folder.ps1 "<path>"` finds the `#32770` dialog owned by the app, sets the `Edit` child with `WM_SETTEXT`, and presses button id 1 (`BM_CLICK`). Works for the legacy 「选择文件夹」 dialog; modern IFileDialog needs the same idea with different control ids.
- Occluded windows: Chromium throttles them, so `cdp.py text` works while `cdp.py shot` hangs. Run `wt.py focus <process>` before a batch of screenshots.
- Linux: `wt.py launch` starts the app in the current real session (`:0`); it does not create a private HOME/DBus or a virtual desktop.

## Native menus and approvals

- Title-bar menus (File/Edit/…) are native Electron menus: not in the DOM and not in the UIA tree. Open them with a real click (`wt.py click` or `cdp.py clickxy`), capture the desktop, and read the items from the image.
- Approval buttons can be split buttons: the main part only opens a menu ("Allow once" / "Allow for this session"), and a second click on the menu item actually approves. Use the real pointer; DOM `.click()` just re-opens the menu.
- A pending approval looks like "running" in some apps (the tool row keeps saying 运行中 while the timer runs). When a task stalls, check for an approval card before blaming the model.

## Evidence paths

- `events.jsonl` stores absolute screenshot paths. Do not rename `screens/*.png` after capture: rename turns `audit` into `shot files FAIL`. Freeze the S-number before the first shot, or keep a copy under the old name.

## Screenshots and attribution

- Crop to the control/panel that proves the row. A 1500px full window scaled to 300×150 makes 12px UI text ~3px; use at least 800×400 for report images and 420×210 for in-cell images.
- Label every image with an evidence type: `实机-正常`, `实机-账号限制`, `实机-额度限制`, `DOM 文本`, `文档`, `重绘`, `无独立截图`.
- Account limits ("current account cannot use this model"), quota exhaustion ("you've hit your usage limit"), and blank/loading pages are environment states, not product defects. Put them in limitations, never in the product issue list.
- One image may support several rows only when it is explicitly marked "same screen evidence" and the caption says which row it proves. A welcome page is not evidence for Rules/SSH/WSL.
- If there is no independent screenshot, write "无独立截图"; do not substitute a nearby screen.
- Before capture, wait for content idle. After capture, read the image and verify it is the right product, page, and state.
- Multiple Electron apps can share the title "Agent"; record `hwnd + pid + title + rect`, minimize overlapping windows, then focus. If `cdp.py shot` times out, focus first and check occlusion before blaming the app.
- Terminal cards redrawn from logs are not screenshots; capture the real terminal window or label the card "重绘".
- Run `wt.py evidence --strict <run>` before delivery: it fails on images below 800×400, missing evidence types, or non-images; `--cells cells.csv` turns an empty cell into `无独立截图` (`no-shot`) instead of a fake image.
