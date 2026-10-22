#!/usr/bin/env python3
"""Take a full-screen screenshot through the XDG desktop portal (GNOME Wayland).

Usage: /usr/bin/python3 harness/portal-shot.py --out shots/full.png
Requires the user to have granted the screenshot permission once; the portal
returns a file URI, which we copy to --out and then delete.
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
# The portal derives the Request path from the caller's unique name + token, so
# it can be predicted and subscribed to before the call: a fast reply would
# otherwise be matched (or dropped) by a handler that ignores the path.
sender = (bus.get_unique_name() or "").lstrip(":").replace(".", "_")
expected = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
opts = {
    "handle_token": GLib.Variant("s", token),
    "interactive": GLib.Variant("b", False),
}
loop = GLib.MainLoop()
state = {"result": None}


def on_response(conn, sender_name, path, iface, signal, params):
    if path != expected:
        return
    state["result"] = params.unpack()
    loop.quit()


bus.signal_subscribe(
    "org.freedesktop.portal.Desktop",
    "org.freedesktop.portal.Request",
    "Response",
    expected,
    None,
    Gio.DBusSignalFlags.NONE,
    on_response,
)
res = bus.call_sync(
    "org.freedesktop.portal.Desktop",
    "/org/freedesktop/portal/desktop",
    "org.freedesktop.portal.Screenshot",
    "Screenshot",
    GLib.Variant("(sa{sv})", ("", opts)),
    None,
    Gio.DBusCallFlags.NONE,
    30000,
    None,
)
handle = res.unpack()[0]
if handle != expected:
    sys.exit(f"unexpected request handle: {handle} (expected {expected})")
GLib.timeout_add_seconds(30, lambda: (loop.quit(), False)[1])
loop.run()
if not state["result"] or state["result"][0] != 0:
    sys.exit(f"screenshot failed: {state['result']}")
uri = state["result"][1]["uri"]
src = urllib.parse.unquote(urllib.parse.urlparse(uri).path)
os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
try:
    shutil.copyfile(src, a.out)
finally:
    # portal leaves the PNG in ~/.cache or /tmp; do not accumulate them
    try:
        os.unlink(src)
    except OSError:
        pass
print(a.out)
