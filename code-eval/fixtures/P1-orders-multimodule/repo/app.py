"""订单服务入口（基线版本）。"""

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import reports
import store

DATA = None
STORE = None


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/health":
            return self._send(200, {"ok": True})
        if path == "/orders":
            return self._send(200, {"orders": STORE.list_orders()})
        if path.startswith("/orders/"):
            try:
                return self._send(200, STORE.get_order(path[len("/orders/"):]))
            except store.NotFound:
                return self._send(404, {"error": "not_found"})
        if path.startswith("/inventory/"):
            try:
                return self._send(200, STORE.inventory(path[len("/inventory/"):]))
            except store.NotFound:
                return self._send(404, {"error": "not_found"})
        if path == "/reports/daily":
            date = (parse_qs(parsed.query).get("date") or [""])[0]
            if not date:
                return self._send(400, {"error": "date_required"})
            return self._send(200, reports.daily(DATA, date))
        if path == "/audit":
            order_id = (parse_qs(parsed.query).get("order_id") or [""])[0]
            return self._send(200, {"events": STORE.audit(order_id)})
        return self._send(404, {"error": "not_found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        match = re.fullmatch(r"/orders/([^/]+)/cancel", parsed.path)
        if not match:
            return self._send(404, {"error": "not_found"})
        try:
            order = STORE.cancel_order(match.group(1))
        except store.NotFound:
            return self._send(404, {"error": "not_found"})
        except store.Conflict as exc:
            return self._send(409, {"error": str(exc)})
        except NotImplementedError:
            return self._send(501, {"error": "not_implemented"})
        except Exception:
            return self._send(500, {"error": "internal_error"})
        return self._send(200, order)


def make_server(host, port, data_dir):
    global DATA, STORE
    DATA = data_dir
    STORE = store.Store(data_dir)
    return ThreadingHTTPServer((host, port), Handler)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    httpd = make_server(a.host, a.port, a.data)
    print(f"LISTENING {httpd.server_address[1]}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
