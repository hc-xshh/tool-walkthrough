#!/usr/bin/env python3
"""Take a full-screen screenshot through the XDG desktop portal (GNOME Wayland).

Usage: /usr/bin/python3 harness/portal-shot.py --out shots/full.png
Requires the user to have granted the screenshot permission once; the portal
returns a file URI, which we copy to --out.
"""
import argparse
import os
import shutil
import sys
import urllib.parse

try:
    from gi.repository import Gio, GLib
except ImportError:
    sys.exit("missing python3-gi; run with /usr/bin/python3 (system python)")

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
a = ap.parse_args()

bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
token = f"walkthrough_shot_{os.getpid()}"
opts = {
    "handle_token": GLib.Variant("s", token),
    "interactive": GLib.Variant("b", False),
}
loop = GLib.MainLoop()
state = {"handle": None, "result": None}

def on_response(conn, sender, path, iface, signal, params):
    if state["handle"] and path != state["handle"]:
        return
    code, results = params.unpack()
    state["result"] = (code, results)
    loop.quit()

bus.signal_subscribe(
    "org.freedesktop.portal.Desktop",
    "org.freedesktop.portal.Request",
    "Response",
    None, None, Gio.DBusSignalFlags.NONE, on_response,
)
res = bus.call_sync(
    "org.freedesktop.portal.Desktop",
    "/org/freedesktop/portal/desktop",
    "org.freedesktop.portal.Screenshot",
    "Screenshot",
    GLib.Variant("(sa{sv})", ("", opts)),
    None, Gio.DBusCallFlags.NONE, 30000, None,
)
state["handle"] = res.unpack()[0]
GLib.timeout_add_seconds(30, lambda: (loop.quit(), False)[1])
loop.run()
if not state["result"] or state["result"][0] != 0:
    sys.exit(f"screenshot failed: {state['result']}")
uri = state["result"][1]["uri"]
src = urllib.parse.unquote(urllib.parse.urlparse(uri).path)
os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
shutil.copyfile(src, a.out)
print(a.out)
