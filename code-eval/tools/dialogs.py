#!/usr/bin/env python3
"""Unknown dialogs: classify, auto-handle the safe ones, stop on the rest.

Drivers run a GUI whose dialogs change between releases (trust prompt, login,
quota, update, terms). Clicking blindly is worse than stopping: one wrong click
can accept a legal agreement, wipe unsaved work, or restart the app mid-run.

So there are three tiers, and the rules are data:

  safe     known, reversible, and required to continue (e.g. trust this folder)
  blocked  needs a human decision (login, quota, terms, unsaved work, restart)
  unknown  visible modal with no matching rule -> stop, screenshot, report

Add a row when a new dialog shows up; never widen `safe` to "whatever button is
in the dialog".
"""
from __future__ import annotations

# marker in page text -> labels to click, in order
SAFE: list[tuple[str, tuple[str, ...]]] = [
    ("信任此作者", ("是，我信任此作者", "信任此作者")),
    ("是否信任", ("是，我信任此作者",)),
    ("稍后提醒", ("稍后", "稍后提醒")),
    ("以后再说", ("以后再说", "稍后再说")),
    ("知道了", ("知道了",)),
]

# marker in page text -> human-readable reason
BLOCKED: list[tuple[str, str]] = [
    ("需要登录", "需要登录"),
    ("请先登录", "需要登录"),
    ("重新登录", "登录失效"),
    ("扫码登录", "需要扫码登录"),
    ("验证码", "需要验证码"),
    ("额度不足", "额度不足"),
    ("余额不足", "余额不足"),
    ("升级套餐", "需要升级套餐"),
    ("服务协议", "需要接受服务协议"),
    ("隐私政策", "需要接受隐私政策"),
    ("是否保存", "有未保存内容"),
    ("保存更改", "有未保存内容"),
    ("立即更新", "要求更新"),
    ("立即重启", "要求重启以更新"),
]


# Qoder's "run this command" confirmation. The button is not a plain "接受":
# 1.37 renders it as "终端运行 Ctrl ↩", with the shortcut glued to the label,
# while older builds used "接受". Matching an exact label misses 1.37, and
# matching a bare "运行" would hit the editor's "运行 Python 文件" toolbar
# button, so the rule is a prefix. Shared by drive_qoder.py and stall.py.
RUN_CONFIRM_PREFIXES: tuple[str, ...] = ("终端运行", "运行命令", "执行命令")


def run_confirm(label: str) -> bool:
    """True when `label` is Qoder's "run this command" button."""
    return (label or "").strip().startswith(RUN_CONFIRM_PREFIXES)


def classify(text: str) -> list[dict]:
    """Rules that match `text`, blocked first (a blocked marker wins)."""
    hits: list[dict] = []
    seen: set[str] = set()
    for marker, reason in BLOCKED:
        if marker in text and marker not in seen:
            seen.add(marker)
            hits.append({"kind": "blocked", "marker": marker, "reason": reason})
    for marker, labels in SAFE:
        if marker in text and marker not in seen:
            seen.add(marker)
            hits.append({"kind": "safe", "marker": marker, "labels": list(labels)})
    return hits


def handle(page_text, click_text, log, where="", shot=None, dom=None) -> tuple[str, dict | None]:
    """Run the rules once.

    Returns ("ok"|"handled"|"blocked"|"unknown", detail). `click_text(label)`
    returns "clicked" on success; `shot()` returns a screenshot path or None;
    `dom()` returns visible modal texts (for the unknown case).
    """
    text = page_text()

    for hit in classify(text):
        if hit["kind"] == "blocked":
            path = shot() if shot else None
            log("dialog_blocked", where=where, marker=hit["marker"],
                reason=hit["reason"], screenshot=path)
            return "blocked", hit
        for label in hit.get("labels", []):
            if click_text(label) == "clicked":
                log("dialog_handled", where=where, marker=hit["marker"], label=label)
                return "handled", {**hit, "label": label}

    if dom is not None:
        try:
            dialogs = [str(d).strip() for d in (dom() or []) if str(d).strip()]
        except Exception:  # noqa: BLE001 - a probe failure must not abort the run
            dialogs = []
        if dialogs:
            path = shot() if shot else None
            log("dialog_unknown", where=where, text=dialogs[0][:200], screenshot=path)
            return "unknown", {"kind": "unknown", "text": dialogs[0][:200], "screenshot": path}

    return "ok", None
