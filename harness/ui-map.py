#!/usr/bin/env python3
"""Enumerate the interactive controls of a running Electron/Chromium app.

Usage:
  python3 harness/ui-map.py --port 9339 --out runs/<run>/ui-map.md
  python3 harness/ui-map.py --port 9339 --match solo-lite --include-unclickable

Writes the body of a page map (one row per control) that `wt.py coverage`
reads back. This is the mechanical half of METHOD Step 1: it finds what is
reachable, a human still decides what to test and what to skip.

Controls are grouped by the nearest landmark ancestor (nav / aside / header /
main / dialog / toolbar / section) so the table reads like the screen.
"""
import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cdp  # noqa: E402

PROBE = r"""
(() => {
  const SEL = [
    'button', 'a[href]', 'input', 'select', 'textarea',
    '[role=button]', '[role=tab]', '[role=menuitem]', '[role=switch]',
    '[role=checkbox]', '[role=radio]', '[role=combobox]', '[role=treeitem]',
    '[role=option]', '[contenteditable=true]', '[tabindex="0"]',
    '[class*=nav-item]', '[class*=menu-item]', '[class*=tab-item]', '[data-testid]'
  ].join(',');
  const TYPE = (el) => {
    const r = (el.getAttribute('role') || '').toLowerCase();
    if (r) return r;
    const t = el.tagName.toLowerCase();
    if (t === 'a') return '链接';
    if (t === 'input') {
      const it = (el.getAttribute('type') || 'text').toLowerCase();
      if (it === 'checkbox') return '勾选';
      if (it === 'radio') return '单选';
      return it === 'text' ? '输入框' : it;
    }
    if (t === 'select') return '下拉';
    if (t === 'textarea') return '输入框';
    if (el.getAttribute('contenteditable') === 'true') return '输入框';
    return '按钮';
  };
  const label = (el) => {
    const cand = [
      el.getAttribute('aria-label'),
      el.getAttribute('title'),
      el.getAttribute('data-testid'),
      (el.innerText || '').replace(/\s+/g, ' ').trim(),
      el.getAttribute('placeholder'),
      el.getAttribute('name'),
    ].find((v) => v && v.trim());
    if (cand) return cand.slice(0, 48);
    const cls = (el.getAttribute('class') || '').split(/\s+/).find(Boolean) || '';
    return '<' + el.tagName.toLowerCase() + (cls ? ' ' + cls.slice(0, 24) : '') + '>';
  };
  const regionOf = (el) => {
    if (el.closest('dialog,[role=dialog]')) return '弹窗';
    const r = el.getBoundingClientRect();
    const W = window.innerWidth, H = window.innerHeight;
    if (r.top < H * 0.07 && r.width < W * 0.9) return '顶部栏';
    if (r.left < W * 0.16) return '左侧栏';
    if (r.top > H * 0.72) return '底部输入区';
    return '主区';
  };
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const ROOT = document.querySelector(__SCOPE__) || document;
  const SEMANTIC = [...ROOT.querySelectorAll(SEL)];
  // Many app shells build clickable rows out of plain divs; cursor:pointer is
  // the only uniform signal. Keep the outermost such element to avoid listing
  // every wrapper, and skip ones inside a real <button>/<a>.
  const POINTER = [...ROOT.querySelectorAll('*')].filter((el) => {
    if (getComputedStyle(el).cursor !== 'pointer') return false;
    const anchor = el.closest('button,a[href]');
    if (anchor && anchor !== el) return false;
    let p = el.parentElement;
    while (p) {
      if (getComputedStyle(p).cursor === 'pointer') return false;
      p = p.parentElement;
    }
    const t = (el.innerText || '').trim();
    return t.length > 0 && t.length <= 60;
  });
  const out = [];
  for (const el of [...SEMANTIC, ...POINTER]) {
    const anchor = el.closest('button,a[href]');
    if (anchor && anchor !== el) continue;  // icon span inside its own button
    const text = label(el);
    const vis = visible(el);
    if (!text && !vis) continue;
    out.push({
      region: regionOf(el),
      text: text,
      type: TYPE(el),
      visible: vis,
      inDialog: !!el.closest('dialog,[role=dialog]'),
      tag: el.tagName.toLowerCase(),
    });
  }
  const seen = new Set();
  return out.filter((c) => {
    const k = c.region + '|' + c.text + '|' + c.type.replace(/^$/, '');
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
})()
"""


def split_nav(text):
    """Return (text without the 导航 block, list of nav row lines)."""
    marker = "## 导航"
    if marker not in text:
        return text, []
    head, _, tail = text.partition(marker)
    rows, rest_lines = [], []
    for line in tail.splitlines():
        s = line.strip()
        if s.startswith("|") and not re.fullmatch(r"\|[\s\-:|]+\|", s) and "从" not in s:
            rows.append(s)
        elif rest_lines or (s and not s.startswith("|")):
            rest_lines.append(line)
    leftover = "\n".join(rest_lines).strip()
    body = head.rstrip()
    if leftover:
        body += "\n\n" + leftover
    return body + "\n", rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9339)
    ap.add_argument("--match", default=None, help="only attach to a target whose URL contains this")
    ap.add_argument("--kind", default="page", choices=["page", "iframe", "any"])
    ap.add_argument("--out", required=True, help="markdown file to write / append to")
    ap.add_argument("--title", default=None, help="section title, e.g. the screen name")
    ap.add_argument("--nav-from", default=None, help="screen you came from, e.g. 'S1 首屏'")
    ap.add_argument("--nav-via", default=None, help="control id you clicked, e.g. U02")
    ap.add_argument("--nav-to", default=None, help="screen this section describes")
    ap.add_argument("--scope", default="body",
                    help="CSS selector to limit the crawl to one popup/panel (default: body)")
    ap.add_argument("--include-unclickable", action="store_true",
                    help="also list controls that exist in the DOM but are not visible")
    a = ap.parse_args()

    c = cdp.CDP(a.port, a.match, a.kind)
    probe = PROBE.replace("__SCOPE__", json.dumps(a.scope))
    items = [i for i in (c.eval(probe) or []) if i.get("type") != "presentation"]
    if not a.include_unclickable:
        items = [i for i in items if i.get("visible")]
    if not items:
        sys.exit("no interactive controls found on this target")

    title = (a.title or f"页面：{a.match or 'main'}").strip()
    if not title:
        sys.exit("--title must not be empty")

    out = pathlib.Path(a.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    raw_existing = out.read_text(encoding="utf-8") if out.exists() else ""
    # template instructions live in HTML comments and contain example tables;
    # drop them so section/nav lookups only see real content
    cleaned = re.sub(r"<!--.*?-->", "", raw_existing, flags=re.S)
    existing, nav_rows = split_nav(cleaned)
    # ids must stay unique across screens; continue after the highest one seen
    used = [int(m) for m in re.findall(r"^\|\s*U(\d+)\s*\|", existing, flags=re.M)]
    first = (max(used) + 1) if used else 1

    rows = []
    for n, it in enumerate(items, start=first):
        state = "可见" if it.get("visible") else "存在但不可见"
        if it.get("inDialog"):
            state += "（弹窗内）"
        rows.append(
            "| U{n:02d} | {region} | {text} | {type} | {state} |  |  |".format(
                n=n,
                region=it.get("region", "").replace("|", "/"),
                text=(it.get("text") or f"<{it.get('tag')}>").replace("|", "/"),
                type=it.get("type", ""),
                state=state,
            )
        )

    block = (
        f"\n## {title}\n\n"
        "| ID | 区域 | 控件 | 类型 | 状态 | 覆盖任务 | 备注 |\n"
        "|---|---|---|---|---|---|---|\n"
        + "\n".join(rows)
        + "\n"
    )
    if f"## {title}" in existing:
        out.write_text(existing, encoding="utf-8")
        sys.exit(f"{out} already has a section titled {title!r}; pick another --title")
    existing += block

    if a.nav_from and a.nav_to:
        nav_rows.append(f"| {a.nav_from} | {a.nav_via or ''} | {a.nav_to} |  | 由 ui-map.py 记录 |")
    if nav_rows:
        existing = existing.rstrip() + (
            "\n\n## 导航\n\n"
            "| 从 | 控件 | 到 | 返回方式 | 备注 |\n"
            "|---|---|---|---|---|\n"
            + "\n".join(nav_rows)
            + "\n"
        )

    out.write_text(existing, encoding="utf-8")
    print(f"{len(rows)} controls -> {out}", file=sys.stderr)
    print(json.dumps({"controls": len(rows), "out": str(out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
