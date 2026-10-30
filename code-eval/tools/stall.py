#!/usr/bin/env python3
"""Diagnose a GUI run that stopped making progress, and try to unstick it.

A driver only sees page text and buttons. When both stop changing it cannot
tell whether the app is thinking, animating, or waiting for a click on a prompt
it does not recognise. This module looks at what is actually on screen:

  * two screenshots ~1.2s apart — identical pixels mean a frozen UI, not a busy
    one (a spinner or streaming text keeps changing);
  * every visible button with its centre, for a precise pointer click;
  * OCR of the screenshot, for text rendered where innerText cannot see it
    (canvas / webgl panels). Skipped cleanly when tesseract is not installed;
  * the same dialog rules the drivers already use (dialogs.classify).

Verdicts:

  handled  a known confirmation is on screen; the caller clicks `label`
           (`via` says whether it came from the DOM or from OCR)
  blocked  a human is needed (login / quota / licence / update) — stop
  unknown  nothing recognised; evidence is on disk for the next fix
  dead     CDP returned no page, no buttons and no screenshot — window gone
"""
from __future__ import annotations

import shutil
import struct
import subprocess
import time
from pathlib import Path

import dialogs

try:  # optional: a coarse pixel diff is nicer than "any byte changed"
    import PIL  # noqa: F401

    HAS_PIL = True
except ImportError:  # pragma: no cover - depends on the host
    HAS_PIL = False


def buttons(cdp) -> list[dict]:
    """Visible buttons with their centre, in viewport coordinates."""
    return cdp.js("""(() => {
      const out = [];
      for (const el of document.querySelectorAll('button,[role="button"],a.monaco-button')) {
        if (!el.offsetParent) continue;
        const r = el.getBoundingClientRect();
        if (r.width < 2 || r.height < 2) continue;
        out.push({
          text: (el.innerText || '').trim().slice(0, 60),
          aria: (el.getAttribute('aria-label') || '').trim().slice(0, 60),
          x: Math.round(r.x + r.width / 2),
          y: Math.round(r.y + r.height / 2),
        });
      }
      return out;
    })()""") or []


def viewport(cdp) -> dict:
    try:
        return cdp.js("(() => ({w: window.innerWidth, h: window.innerHeight}))()") or {}
    except Exception:  # noqa: BLE001 - diagnostics must never mask the stall
        return {}


def png_size(path: Path) -> tuple[int, int]:
    try:
        with open(path, "rb") as fh:
            head = fh.read(24)
        if len(head) >= 24 and head[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", head[16:24])
    except OSError:
        pass
    return (0, 0)


def same_image(a: Path, b: Path) -> bool:
    """True when two screenshots are effectively identical.

    Byte equality first (cheap and exact); a coarse grayscale diff when Pillow
    is available, so a blinking caret does not read as "still animating".
    """
    try:
        if Path(a).read_bytes() == Path(b).read_bytes():
            return True
    except OSError:
        return False
    if not HAS_PIL:
        return False
    try:
        from PIL import Image, ImageChops

        with Image.open(a) as left, Image.open(b) as right:
            one = left.convert("L").resize((64, 64))
            two = right.convert("L").resize((64, 64))
            delta = ImageChops.difference(one, two)
            return sum(delta.getdata()) / (64 * 64) < 0.6
    except Exception:  # noqa: BLE001 - missing Pillow means "different"
        return False


def _parse_tsv(text: str) -> list[dict]:
    words = []
    for line in text.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 12 or parts[0] != "5":
            continue
        try:
            conf = float(parts[10])
            left, top, width, height = (int(parts[i]) for i in range(6, 10))
        except ValueError:
            continue
        word = parts[11].strip()
        if not word or conf < 40:
            continue
        words.append({"text": word, "x": left, "y": top, "w": width, "h": height})
    return words


def ocr_words(path: Path, timeout: int = 60) -> list[dict] | None:
    """Words with pixel boxes, or None when OCR is unavailable."""
    exe = shutil.which("tesseract")
    if not exe or not Path(path).is_file():
        return None
    for lang in ("chi_sim+eng", "eng"):
        try:
            proc = subprocess.run(
                [exe, str(path), "stdout", "-l", lang, "--psm", "11", "tsv"],
                capture_output=True, text=True, timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode == 0:
            return _parse_tsv(proc.stdout)
    return None


def screenshot(cdp, path: Path) -> bool:
    try:
        proc = cdp.run("shot", str(path), timeout=30)
    except Exception:  # noqa: BLE001 - a closed window is a valid diagnosis
        return False
    return proc.returncode == 0 and Path(path).is_file() and Path(path).stat().st_size > 0


def classify(text: str, visible: list[dict], words: list[dict] | None) -> dict:
    """Decide what the screen is waiting for."""
    haystack = text + "\n" + "\n".join(word["text"] for word in (words or []))
    hits = dialogs.classify(haystack)

    for hit in hits:
        if hit["kind"] == "blocked":
            return {"verdict": "blocked", "reason": hit["reason"]}

    dom = {item["text"] for item in visible} | {item["aria"] for item in visible if item["aria"]}
    for hit in hits:
        if hit["kind"] != "safe":
            continue
        for label in hit["labels"]:
            if label in dom:
                return {"verdict": "handled", "label": label,
                        "reason": hit["marker"], "via": "dom"}
            if any(word["text"] == label for word in (words or [])):
                return {"verdict": "handled", "label": label,
                        "reason": hit["marker"], "via": "ocr"}

    # Qoder's command confirmation: "终端运行 / 拒绝 / 接受". It is not in the
    # shared dialog rules because the wording is product-specific.
    if any(marker in haystack for marker in ("终端运行", "运行命令", "执行命令")):
        for label in ("接受", "允许运行", "允许"):
            if label in dom:
                return {"verdict": "handled", "label": label, "reason": "终端运行", "via": "dom"}
            if any(word["text"] == label for word in (words or [])):
                return {"verdict": "handled", "label": label, "reason": "终端运行", "via": "ocr"}

    return {"verdict": "unknown"}


def _render(report: dict, text: str, visible: list[dict], words: list[dict] | None) -> str:
    lines = [
        f"stall evidence {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"verdict: {report.get('verdict')}",
        f"reason: {report.get('reason') or '-'}",
        f"frozen: {report.get('frozen')}",
        f"ocr: {'yes' if words else 'unavailable (tesseract not installed?)'}",
        "",
        "## page text",
        text[-4000:] or "(empty)",
        "",
        "## visible buttons",
    ]
    for item in visible:
        label = item["text"] or item["aria"] or "(unlabeled)"
        lines.append(f"- {label} @ {item['x']},{item['y']}")
    lines += ["", "## ocr words"]
    for word in (words or [])[:80]:
        lines.append(f"- {word['text']} @ {word['x']},{word['y']} {word['w']}x{word['h']}")
    return "\n".join(lines) + "\n"


def diagnose(cdp, out_dir: Path, tag: str, text: str = "") -> dict:
    """Capture the screen, classify it, and write one evidence report."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    shot = out_dir / f"{tag}.png"
    second = out_dir / f".{tag}.b.png"

    has_shot = screenshot(cdp, shot)
    time.sleep(1.2)
    has_second = screenshot(cdp, second)
    frozen = bool(has_shot and has_second and same_image(shot, second))
    second.unlink(missing_ok=True)
    if not has_shot:
        shot.unlink(missing_ok=True)

    if not text:
        try:
            text = cdp.text()
        except Exception:  # noqa: BLE001
            text = ""
    visible = buttons(cdp)
    words = ocr_words(shot) if has_shot else None

    if not has_shot and not text and not visible:
        verdict = {"verdict": "dead", "reason": "CDP 没有返回页面、按钮或截图"}
    else:
        verdict = classify(text, visible, words)

    report = {
        **verdict,
        "frozen": frozen,
        "ocr": bool(words),
        "shot": str(shot) if has_shot else None,
        "evidence": str(out_dir / f"{tag}.txt"),
    }

    if verdict.get("verdict") == "handled" and verdict.get("via") == "ocr":
        word = next((item for item in (words or []) if item["text"] == verdict["label"]), None)
        size = png_size(shot) if has_shot else (0, 0)
        size_css = viewport(cdp)
        if word and size[0] and size_css.get("w"):
            scale = size[0] / size_css["w"]
            report["click"] = {
                "x": round((word["x"] + word["w"] / 2) / scale),
                "y": round((word["y"] + word["h"] / 2) / scale),
            }

    Path(report["evidence"]).write_text(_render(report, text, visible, words), encoding="utf-8")
    return report
