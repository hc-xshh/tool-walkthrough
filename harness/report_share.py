#!/usr/bin/env python3
"""Share a Markdown report without breaking its images.

Why this exists (2026-10-29):
  - A Markdown file only carries relative image paths; sending the .md alone
    gives the recipient a page of broken images.
  - PDF and single-file HTML are the safe "send one file" formats. HTML embeds
    every image as a data URI, so it also works as an email attachment.
  - DingTalk Docs' official Markdown guide only documents `![](http://...)`;
    in practice it also accepts `data:image/png;base64,...` on import. Base64
    keeps the report private (no public image host) but makes the file large.
  - 480px JPEG table thumbnails look blurry when zoomed. Prefer original PNGs
    for DingTalk; use compact JPEG only when the upload size matters.

Usage:
  python harness/report_share.py report.md --outdir dist --html --pdf
  python harness/report_share.py report.md --outdir dist --dingtalk original
  python harness/report_share.py report.md --outdir dist --all

Requires: markdown, Pillow (already in harness/requirements.txt), and
Chrome/Edge for --pdf.
"""
from __future__ import annotations

import argparse
import base64
import io
import mimetypes
import os
import re
import subprocess
import tempfile
from pathlib import Path

import markdown
from PIL import Image

IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def _looks_local(src: str) -> bool:
    return not src.startswith(("http://", "https://", "data:"))


def _find_original(src: Path, root: Path) -> Path:
    """A report may point at a small thumbs/ image; prefer the full-size sibling."""
    if "thumbs" not in src.parts:
        return src
    for candidate in root.rglob(src.name):
        if "thumbs" not in candidate.parts and "node_modules" not in candidate.parts:
            return candidate
    return src


def _data_uri(path: Path, mode: str, width: int, quality: int) -> str:
    if mode == "original":
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")

    im = Image.open(path).convert("RGB")
    w, h = im.size
    if w > width:
        im = im.resize((width, max(1, int(h * width / w))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def inline_images(text: str, root: Path, mode: str = "original", width: int = 1400,
                  quality: int = 86) -> tuple[str, int, int]:
    """Replace local image paths with data URIs. Returns (text, inlined, missing)."""
    stats = {"inlined": 0, "missing": 0}

    def repl(match: re.Match) -> str:
        alt, src = match.group(1), match.group(2)
        if not _looks_local(src):
            return match.group(0)
        path = (root / src).resolve()
        if not path.exists():
            stats["missing"] += 1
            print(f"  ! missing image: {src}")
            return match.group(0)
        path = _find_original(path, root)
        stats["inlined"] += 1
        return f"![{alt}]({_data_uri(path, mode, width, quality)})"

    return IMAGE_RE.sub(repl, text), stats["inlined"], stats["missing"]


CSS = """
:root { color-scheme: light; }
body { font-family: -apple-system, "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
  max-width: 1180px; margin: 36px auto; padding: 0 28px; color: #1f2328;
  line-height: 1.68; font-size: 15px; }
h1 { font-size: 30px; line-height: 1.25; border-bottom: 2px solid #d8dee4; padding-bottom: 12px; }
h2 { font-size: 22px; margin-top: 38px; border-bottom: 1px solid #d8dee4; padding-bottom: 7px; }
h3 { font-size: 17px; margin-top: 28px; }
table { border-collapse: collapse; width: 100%; margin: 16px 0 20px; font-size: 13px; }
th, td { border: 1px solid #d0d7de; padding: 8px 10px; vertical-align: top; text-align: left; }
th { background: #f6f8fa; white-space: nowrap; }
tr:nth-child(even) td { background: #fcfcfd; }
img { max-width: 100%; height: auto; border: 1px solid #d0d7de; border-radius: 5px; margin: 10px 0; background: #fff; }
code { background: #f6f8fa; padding: 2px 5px; border-radius: 4px; font-family: Consolas, "Cascadia Mono", monospace; font-size: 90%; }
pre { background: #f6f8fa; border: 1px solid #e5e7eb; padding: 12px 14px; border-radius: 6px; overflow: auto; }
pre code { background: none; padding: 0; }
blockquote { border-left: 4px solid #d0d7de; margin: 14px 0; padding: 4px 16px; color: #57606a; background: #f6f8fa; }
hr { border: 0; border-top: 1px solid #d8dee4; margin: 30px 0; }
em { color: #57606a; }
@page { size: A4; margin: 14mm 12mm; }
@media print {
  body { max-width: none; margin: 0; padding: 0; font-size: 11pt; line-height: 1.55; }
  h2 { page-break-after: avoid; } h3 { page-break-after: avoid; }
  table { font-size: 9pt; } th, td { padding: 5px 6px; }
  img { page-break-inside: avoid; } tr { page-break-inside: avoid; }
  pre { white-space: pre-wrap; } a { color: inherit; text-decoration: none; }
}
"""


def md_to_html(text: str, root: Path, title: str, mode: str = "original",
               width: int = 1400, quality: int = 86) -> str:
    inlined, n, missing = inline_images(text, root, mode=mode, width=width, quality=quality)
    body = markdown.markdown(inlined, extensions=["tables", "fenced_code", "sane_lists", "toc"],
                             output_format="html5")
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title><style>{CSS}</style></head><body>{body}</body></html>
"""


def _find_browser(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    candidates = [
        os.environ.get("CHROME"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ]
    return next((p for p in candidates if p and Path(p).exists()), None)


def html_to_pdf(html_path: Path, pdf_path: Path, browser: str | None = None) -> None:
    exe = _find_browser(browser)
    if not exe:
        raise SystemExit("No Chrome/Edge found; pass --browser or install one.")
    with tempfile.TemporaryDirectory(prefix="report-share-") as profile:
        cmd = [
            exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
            f"--user-data-dir={profile}", f"--print-to-pdf={pdf_path}",
            html_path.resolve().as_uri(),
        ]
        subprocess.run(cmd, check=True, timeout=180,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not pdf_path.exists() or pdf_path.stat().st_size < 10_000:
        raise SystemExit(f"PDF looks empty: {pdf_path}")


def build_dingtalk(text: str, root: Path, out: Path, mode: str, width: int, quality: int) -> None:
    inlined, n, missing = inline_images(text, root, mode=mode, width=width, quality=quality)
    note = (
        "\n> **单文件版**：图片已以 base64 内嵌，可直接上传到钉钉文档；"
        + ("原图未压缩。" if mode == "original" else f"等比压缩到 {width}px（未裁剪）。")
        + "\n"
    )
    inlined = inlined.replace("所有截图均为窗口原图，未裁剪\n",
                              "所有截图均为窗口原图，未裁剪\n" + note, 1)
    out.write_text(inlined, encoding="utf-8")
    print(f"  {out.name}: {out.stat().st_size/1024/1024:.2f} MB, {n} images inlined, {missing} missing")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report", help="Markdown file to share")
    ap.add_argument("--outdir", default="dist")
    ap.add_argument("--title", default=None)
    ap.add_argument("--html", action="store_true", help="write a single-file HTML")
    ap.add_argument("--pdf", action="store_true", help="write a PDF via Chrome/Edge")
    ap.add_argument("--dingtalk", choices=["original", "compact"], help="write a single-file MD for DingTalk")
    ap.add_argument("--all", action="store_true", help="html + pdf + dingtalk original")
    ap.add_argument("--width", type=int, default=1400, help="compact image width (default 1400)")
    ap.add_argument("--quality", type=int, default=86, help="compact JPEG quality (default 86)")
    ap.add_argument("--browser", default=None)
    args = ap.parse_args()

    report = Path(args.report).resolve()
    root = report.parent
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    text = report.read_text(encoding="utf-8")
    title = args.title or report.stem
    stem = report.stem

    if args.all:
        args.html = args.pdf = True
        args.dingtalk = args.dingtalk or "original"
    if not (args.html or args.pdf or args.dingtalk):
        args.html = args.pdf = True

    html_path = outdir / f"{stem}.html"
    if args.html or args.pdf:
        html = md_to_html(text, root, title)
        html_path.write_text(html, encoding="utf-8")
        print(f"  {html_path.name}: {html_path.stat().st_size/1024/1024:.2f} MB")
    if args.pdf:
        pdf_path = outdir / f"{stem}.pdf"
        html_to_pdf(html_path, pdf_path, args.browser)
        print(f"  {pdf_path.name}: {pdf_path.stat().st_size/1024/1024:.2f} MB")
        if not args.html:
            html_path.unlink(missing_ok=True)

    if args.dingtalk:
        out = outdir / f"{stem}-dingtalk.md" if args.dingtalk == "original" else outdir / f"{stem}-dingtalk-compact.md"
        build_dingtalk(text, root, out, args.dingtalk, args.width, args.quality)


if __name__ == "__main__":
    main()
