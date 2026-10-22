#!/usr/bin/env python3
"""Render a run's report.md to PDF (via headless Chrome), with evidence screenshots.

Usage:
  ./harness/build-report.py runs/<date>-<tool>
  ./harness/build-report.py <run-dir> --out report.pdf
  ./harness/build-report.py <run-dir> --exclude 't6-*' --no-appendix

Intermediate HTML is written to a temp dir, never into the run directory:
the sources of truth are report.md + shots/, the PDF is the derived artifact.

Every PNG in shots/ is appended as evidence unless excluded. Keep payment
screens, QR codes and account data out of a shared PDF with --exclude, or list
globs under the "exclude" key of shots/captions.json. Identical images are
embedded once. Captions come from shots/captions.json ({"02-home.png": "..."}),
falling back to the file name.
"""
import argparse
import base64
import fnmatch
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from html import escape as html_escape

import markdown

# ![alt](shots/01.png) -> inline data URI, so the temp-dir HTML still has images
MD_IMAGE = re.compile(r"(!\[[^\]]*\]\()([^)\s]+)(\))")
MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}


def inline_local_images(md_text, run):
    """Embed images referenced from report.md; Chrome prints from a temp dir."""

    def repl(m):
        head, src, tail = m.group(1), m.group(2), m.group(3)
        if src.startswith(("data:", "http://", "https://", "#")):
            return m.group(0)
        path = (run / src).resolve()
        mime = MIME.get(path.suffix.lower().lstrip("."))
        if not mime or not path.is_file():
            return m.group(0)
        b64 = base64.b64encode(path.read_bytes()).decode()
        return f"{head}data:{mime};base64,{b64}{tail}"

    return MD_IMAGE.sub(repl, md_text)


STANDALONE_IMG = re.compile(r"<p>\s*(<img\b[^>]*>)\s*</p>", re.IGNORECASE)


def figure_standalone_images(html):
    """A paragraph holding only an image becomes a captioned figure.

    Body screenshots used to render at natural size (then got clipped) and
    without a caption, unlike the appendix figures.
    """

    def repl(m):
        tag = m.group(1)
        alt = re.search(r'alt="([^"]*)"', tag)
        cap = html_escape(alt.group(1)) if alt and alt.group(1).strip() else ""
        caption = f"<figcaption>{cap}</figcaption>" if cap else ""
        return f"<figure>{tag}{caption}</figure>"

    return STANDALONE_IMG.sub(repl, html)



def find_chrome():
    env = os.environ.get("WALKTHROUGH_CHROME")
    if env and pathlib.Path(env).exists():
        return env
    if sys.platform == "darwin":
        for p in (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ):
            if pathlib.Path(p).exists():
                return p
    if sys.platform.startswith("win"):
        bases = [
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
            os.environ.get("LocalAppData"),
        ]
        rels = [
            r"Google\Chrome\Application\chrome.exe",
            r"Chromium\Application\chrome.exe",
            r"Microsoft\Edge\Application\msedge.exe",
        ]
        for base in filter(None, bases):
            for rel in rels:
                p = pathlib.Path(base) / rel
                if p.exists():
                    return str(p)
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome", "msedge"):
        p = shutil.which(name)
        if p:
            return p
    return "google-chrome"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--out", default="report.pdf")
    ap.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                    help="leave shots matching this glob out of the appendix "
                         "(repeatable), e.g. --exclude 't6-01*'")
    ap.add_argument("--no-appendix", action="store_true",
                    help="do not append the evidence-screenshot appendix at all")
    ap.add_argument("--max-figure-height", default="105mm",
                    help="cap each appendix figure so two fit on a page (default 105mm)")
    a = ap.parse_args()

    run = pathlib.Path(a.run_dir).resolve()
    md_text = (run / "report.md").read_text(encoding="utf-8")
    md_text = inline_local_images(md_text, run)
    body = markdown.markdown(md_text, extensions=["tables", "fenced_code", "sane_lists"])
    body = figure_standalone_images(body)

    caps, excludes = {}, list(a.exclude)
    cap_file = run / "shots" / "captions.json"
    if cap_file.exists():
        raw = json.loads(cap_file.read_text(encoding="utf-8-sig"))
        if isinstance(raw, dict):
            # "exclude" (list of globs) is a directive, every other key is a caption
            excludes += list(raw.pop("exclude", []) or [])
            caps = {k: v for k, v in raw.items() if isinstance(v, str)}

    figs, seen, skipped = [], set(), []
    for p in sorted((run / "shots").glob("*.png")):
        if any(fnmatch.fnmatch(p.name, pat) for pat in excludes):
            skipped.append(p.name)
            continue
        data = p.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen:
            skipped.append(f"{p.name} (duplicate)")
            continue
        seen.add(digest)
        b64 = base64.b64encode(data).decode()
        cap = caps.get(p.name) or p.stem.replace("-", " ")
        figs.append(
            f'<figure><img src="data:image/png;base64,{b64}">'
            f'<figcaption>图 {len(figs) + 1} · {html_escape(cap)}</figcaption></figure>'
        )

    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    appendix = "" if a.no_appendix else f'<div class="shots"><h2>证据截图</h2>{"".join(figs)}</div>'
    footer = f'<div class="footer">由 harness/build-report.py 生成于 {stamp} · 运行目录 <code>{html_escape(run.name)}</code></div>'

    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<base href="{run.as_uri()}/">
<title>{html_escape(run.name)}</title>
<style>
  @page {{ size: A4; margin: 16mm 16mm 18mm; }}
  html {{ -webkit-print-color-adjust: exact; }}
  body {{ font-family: "Noto Sans CJK SC", "Noto Sans SC", sans-serif;
         font-size: 10.5pt; line-height: 1.75; color: #1a1a1a;
         max-width: 172mm; margin: 0 auto; }}
  h1 {{ font-size: 20pt; margin: 0 0 6mm; padding-bottom: 3mm; border-bottom: 2px solid #111; }}
  h2 {{ font-size: 13pt; margin: 7mm 0 2mm; padding-left: 3mm; border-left: 3px solid #111; }}
  h3 {{ font-size: 11pt; margin: 5mm 0 1.5mm; color: #333; }}
  p, li {{ margin: 1.2mm 0; }}
  ul, ol {{ padding-left: 6mm; }}
  code {{ font-family: "DejaVu Sans Mono", monospace; font-size: 9pt; background: #f2f2f2;
          padding: 0.4mm 1.2mm; border-radius: 2px; overflow-wrap: anywhere; }}
  /* body images used to render at natural size and got clipped on the right */
  img {{ max-width: 100%; height: auto; }}
  table {{ border-collapse: collapse; width: 100%; margin: 3mm 0; font-size: 9.5pt; }}
  th, td {{ border: 1px solid #d0d0d0; padding: 1.6mm 2mm; text-align: left; vertical-align: top;
            overflow-wrap: anywhere; }}
  th {{ background: #f6f6f6; white-space: nowrap; }}
  blockquote {{ margin: 3mm 0; padding: 2mm 3mm; border-left: 3px solid #999; color: #444; background: #fafafa; }}
  figure {{ margin: 3mm 0; page-break-inside: avoid; text-align: center; }}
  figure img {{ max-width: 100%; max-height: {a.max_figure_height}; width: auto;
                border: 1px solid #ddd; border-radius: 3px; }}
  figcaption {{ font-size: 8.8pt; color: #666; margin-top: 1.2mm; text-align: center; }}
  .shots h2 {{ page-break-before: always; }}
  .footer {{ margin-top: 8mm; padding-top: 2mm; border-top: 1px solid #ddd;
             font-size: 8pt; color: #888; }}
</style></head><body>
{body}
{appendix}
{footer}
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        html_path = pathlib.Path(td) / "report.html"
        html_path.write_text(html, encoding="utf-8")
        out = (run / a.out).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        chrome = find_chrome()
        # A private profile: printing through the user's live profile fails
        # ("exit 21") whenever Chrome is already running.
        profile = pathlib.Path(td) / "chrome-profile"
        cmd = [
            chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
            f"--user-data-dir={profile}",
            "--no-pdf-header-footer", f"--print-to-pdf={out}", html_path.as_uri(),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if proc.returncode != 0:
            sys.exit(
                f"chrome failed (exit {proc.returncode}) printing {out}\n"
                f"{(proc.stderr or proc.stdout or '').strip()[:1500]}"
            )
        if not out.exists():
            sys.exit(f"chrome exited 0 but wrote no PDF: {out}")
    if skipped:
        print(f"appendix skipped {len(skipped)}: {', '.join(skipped)}", file=sys.stderr)
    print(out, out.stat().st_size)


if __name__ == "__main__":
    main()
