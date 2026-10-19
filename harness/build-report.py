#!/usr/bin/env python3
"""Render a run's report.md to PDF (via headless Chrome), with evidence screenshots.

Usage:
  ./harness/build-report.py runs/<date>-<tool>
  ./harness/build-report.py <run-dir> --out report.pdf

Intermediate HTML is written to a temp dir, never into the run directory:
the sources of truth are report.md + shots/, the PDF is the derived artifact.
Captions come from <run>/shots/captions.json ({"02-home.png": "..."}), falling
back to the file name.
"""
import argparse
import base64
import json
import os
import pathlib
import shutil
import subprocess
import tempfile

import markdown


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--out", default="report.pdf")
    a = ap.parse_args()

    run = pathlib.Path(a.run_dir).resolve()
    md_text = (run / "report.md").read_text(encoding="utf-8")
    body = markdown.markdown(md_text, extensions=["tables", "fenced_code", "sane_lists"])

    caps = {}
    cap_file = run / "shots" / "captions.json"
    if cap_file.exists():
        caps = json.loads(cap_file.read_text(encoding="utf-8"))

    figs = []
    for p in sorted((run / "shots").glob("*.png")):
        b64 = base64.b64encode(p.read_bytes()).decode()
        cap = caps.get(p.name, p.stem)
        figs.append(f'<figure><img src="data:image/png;base64,{b64}"><figcaption>{cap}</figcaption></figure>')

    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>{run.name}</title>
<style>
  @page {{ size: A4; margin: 18mm 16mm 16mm; }}
  html {{ -webkit-print-color-adjust: exact; }}
  body {{ font-family: "Noto Sans CJK SC", "Noto Sans SC", sans-serif;
         font-size: 10.5pt; line-height: 1.75; color: #1a1a1a; max-width: 820px; margin: 0 auto; }}
  h1 {{ font-size: 20pt; margin: 0 0 6mm; padding-bottom: 3mm; border-bottom: 2px solid #111; }}
  h2 {{ font-size: 13pt; margin: 7mm 0 2mm; padding-left: 3mm; border-left: 3px solid #111; }}
  h3 {{ font-size: 11pt; margin: 5mm 0 1.5mm; color: #333; }}
  p, li {{ margin: 1.2mm 0; }}
  ul, ol {{ padding-left: 6mm; }}
  code {{ font-family: "DejaVu Sans Mono", monospace; font-size: 9pt; background: #f2f2f2;
          padding: 0.4mm 1.2mm; border-radius: 2px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 3mm 0; font-size: 9.5pt; }}
  th, td {{ border: 1px solid #d0d0d0; padding: 1.6mm 2mm; text-align: left; vertical-align: top; }}
  th {{ background: #f6f6f6; }}
  blockquote {{ margin: 3mm 0; padding: 2mm 3mm; border-left: 3px solid #999; color: #444; background: #fafafa; }}
  figure {{ margin: 4mm 0; page-break-inside: avoid; }}
  figure img {{ width: 100%; border: 1px solid #ddd; border-radius: 3px; }}
  figcaption {{ font-size: 8.8pt; color: #666; margin-top: 1.2mm; text-align: center; }}
  .shots h2 {{ page-break-before: always; }}
</style></head><body>
{body}
<div class="shots"><h2>证据截图</h2>{''.join(figs)}</div>
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        html_path = pathlib.Path(td) / "report.html"
        html_path.write_text(html, encoding="utf-8")
        out = (run / a.out).resolve()
        chrome = (os.environ.get("WALKTHROUGH_CHROME")
                  or shutil.which("google-chrome")
                  or shutil.which("chromium")
                  or "google-chrome")
        subprocess.run([
            chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
            "--no-pdf-header-footer", f"--print-to-pdf={out}", f"file://{html_path}",
        ], check=True, capture_output=True, timeout=180)
    print(out, out.stat().st_size)


if __name__ == "__main__":
    main()
