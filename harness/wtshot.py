#!/usr/bin/env python3
"""Screen capture and the pixel <-> click coordinate mapping."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from wtlib import OS, which_any

__all__ = [
    "enable_dpi_awareness", "desktop_metrics", "shot_meta_path", "read_shot_meta",
    "capture_screen", "_png_size", "_x11_size", "_macos_logical_size",
]

def enable_dpi_awareness():
    """Make this process DPI-aware so screenshot pixels and click coords agree.

    Windows only. A non-aware process gets its coordinates virtualised by the
    shell, so a click lands off-target on any display scaled above 100%.
    """
    if OS != "Windows":
        return None
    import ctypes

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):  # per-monitor v2
            return "per-monitor-v2"
    except Exception:
        pass
    try:
        shcore = ctypes.WinDLL("shcore")
        shcore.SetProcessDpiAwareness.argtypes = [ctypes.c_int]
        shcore.SetProcessDpiAwareness.restype = ctypes.c_int
        if shcore.SetProcessDpiAwareness(2) == 0:  # per-monitor
            return "per-monitor"
    except Exception:
        pass
    try:
        if ctypes.windll.user32.SetProcessDPIAware():
            return "system"
    except Exception:
        pass
    return None




def _x11_size(display):
    """Screen size in pixels, straight from the X server."""
    p = which_any(["xdpyinfo"])
    if not p:
        return (0, 0)
    try:
        out = subprocess.run([p, "-display", display], capture_output=True, text=True, timeout=15)
        m = re.search(r"dimensions:\s+(\d+)x(\d+)", out.stdout or "")
        return (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    except Exception:
        return (0, 0)




def _png_size(png):
    """Read width/height out of a PNG header without extra dependencies."""
    try:
        with open(png, "rb") as fh:
            head = fh.read(24)
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            return (0, 0)
        return (int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big"))
    except Exception:
        return (0, 0)




def _macos_logical_size():
    """Desktop size in points (Finder reports the same units clicks use)."""
    try:
        p = subprocess.run(
            ["osascript", "-e", 'tell application "Finder" to get bounds of window of desktop'],
            capture_output=True, text=True, timeout=15,
        )
        nums = [int(x) for x in re.findall(r"-?\d+", p.stdout or "")]
        if len(nums) >= 4:
            return (nums[2] - nums[0], nums[3] - nums[1])
    except Exception:
        pass
    return (0, 0)




def desktop_metrics(png=None):
    """Map screenshot pixels onto click coordinates.

    `origin` is where pixel (0,0) of the capture sits in the coordinate space
    the click API uses; `scale` is capture pixels per click unit. Windows grabs
    the whole virtual desktop (negative origins with a left-hand secondary
    monitor); macOS captures physical pixels while clicks use points (Retina).
    """
    if OS == "Windows":
        enable_dpi_awareness()
        import ctypes

        g = ctypes.windll.user32.GetSystemMetrics
        return {
            "origin_x": g(76), "origin_y": g(77),  # SM_XVIRTUALSCREEN / SM_YVIRTUALSCREEN
            "width": g(78), "height": g(79),
            "scale": 1.0,
            "source": "GetSystemMetrics(virtual screen)",
        }
    if OS == "Darwin":
        lw, lh = _macos_logical_size()
        pw, ph = _png_size(png) if png else (0, 0)
        scale = round(pw / lw, 3) if lw and pw else 1.0
        return {
            "origin_x": 0, "origin_y": 0,
            "width": pw or lw, "height": ph or lh,
            "scale": scale,
            "source": "screencapture + Finder bounds",
        }
    w, h = _png_size(png) if png else (0, 0)
    return {"origin_x": 0, "origin_y": 0, "width": w, "height": h, "scale": 1.0, "source": "x11"}




def shot_meta_path(png):
    return Path(str(png) + ".json")




def read_shot_meta(png):
    path = shot_meta_path(png)
    if not path.exists():
        return None
    try:
        # utf-8-sig: hand-edited sidecars (e.g. PowerShell) often carry a BOM
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None




def _wayland_session():
    """True when this process is inside a Wayland session (XWayland included)."""
    return (os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
            or bool(os.environ.get("WAYLAND_DISPLAY")))


def _portal_screenshot(out):
    """Capture the composited screen through xdg-desktop-portal.

    x11grab only sees the X11 root window. Under GNOME Wayland the app
    windows live in the compositor, so x11grab produces a black frame even
    though xdotool can still see XWayland window geometry. The portal is the
    only supported way to get the real pixels.
    """
    helper = Path(__file__).with_name("portal-shot.py")
    py = "/usr/bin/python3" if Path("/usr/bin/python3").exists() else sys.executable
    subprocess.run([py, str(helper), "--out", str(out)], check=True)


def capture_screen(out, disp=":0", geom=""):
    """Grab the screen to `out` and return its desktop metadata."""
    out = Path(out)
    portal = False
    if OS == "Linux":
        if str(disp).split(".")[0] != ":0":
            raise SystemExit(
                f"virtual displays are disabled ({disp}); use the real desktop DISPLAY=:0"
            )
        # In a Wayland session :0 is the real desktop; x11grab would be black.
        # A real X11 session keeps the x11grab path; only Wayland needs the portal.
        portal = (disp == ":0" and _wayland_session()
                  and (not geom or geom == "screen")
                  and os.environ.get("WT_SCREENSHOT", "").lower() != "x11")
        if portal:
            try:
                _portal_screenshot(out)
            except (OSError, subprocess.CalledProcessError) as exc:
                raise SystemExit(
                    "wayland screenshot failed: xdg-desktop-portal returned no image; "
                    "grant the screenshot permission once, then retry"
                ) from exc
        else:
            if not geom or geom == "screen":
                w, h = _x11_size(disp)
                geom = f"{w}x{h}" if w and h else "1440x900"
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "x11grab", "-video_size", geom, "-i", disp,
                    "-frames:v", "1", "-y", str(out),
                ],
                check=True, env=dict(os.environ, DISPLAY=disp),
            )
    elif OS == "Darwin":
        subprocess.run(["screencapture", "-x", "-o", str(out)], check=True)
    elif OS == "Windows":
        ps = r'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
# Be DPI-aware before measuring, otherwise SystemInformation reports a
# virtualised (logical) size while CopyFromScreen grabs physical pixels.
$sig = @"
using System;
using System.Runtime.InteropServices;
public class WtDpi {
  [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr v);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
"@
try { Add-Type -TypeDefinition $sig -ErrorAction Stop } catch {}
try { [WtDpi]::SetProcessDpiAwarenessContext([IntPtr](-4)) | Out-Null }
catch { try { [WtDpi]::SetProcessDPIAware() | Out-Null } catch {} }
$vs = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $vs.Width, $vs.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($vs.Left, $vs.Top, 0, 0, $bmp.Size)
$bmp.Save($env:WT_OUT, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
'''
        with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8") as f:
            f.write(ps)
            script = f.name
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script],
                check=True, env=dict(os.environ, WT_OUT=str(out)),
            )
        finally:
            os.unlink(script)
    else:
        raise SystemExit(f"unsupported OS: {OS}")

    meta = desktop_metrics(out)
    pw, ph = _png_size(out)
    if portal:
        # Portal returns the composited image in physical pixels. Compare it
        # with the X server's logical size to keep click --shot correct under
        # fractional scaling instead of assuming a 1.0 ratio.
        lw, lh = _x11_size(disp)
        meta = {
            "origin_x": 0, "origin_y": 0,
            "width": pw or lw, "height": ph or lh,
            "scale": round(pw / lw, 3) if lw and pw else 1.0,
            "source": "xdg-desktop-portal",
        }
    meta["width"] = meta.get("width") or pw
    meta["height"] = meta.get("height") or ph
    meta["screenshot"] = str(out)
    shot_meta_path(out).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


