"""参考解：记账应用入口，HTTP API + 静态前端。"""

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import store

HERE = Path(__file__).resolve().parent
WEB = HERE / "web"
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

    def _file(self, name, content_type):
        path = WEB / name
        if not path.exists():
            return self._send(404, {"error": "not_found"})
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _csv(self, text):
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/":
            return self._file("index.html", "text/html; charset=utf-8")
        if path == "/app.js":
            return self._file("app.js", "text/javascript; charset=utf-8")
        if path == "/styles.css":
            return self._file("styles.css", "text/css; charset=utf-8")
        if path == "/health":
            return self._send(200, {"ok": True})
        month = (query.get("month") or [None])[0]
        try:
            if path == "/expenses":
                return self._send(200, {"expenses": STORE.list_expenses(month)})
            if path == "/summary":
                return self._send(200, STORE.summary(month))
            if path == "/export.csv":
                return self._csv(STORE.export_csv(month))
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})
        match = re.fullmatch(r"/expenses/(\d+)", path)
        if match:
            row = STORE.get_expense(int(match.group(1)))
            if not row:
                return self._send(404, {"error": "not_found"})
            return self._send(200, row)
        return self._send(404, {"error": "not_found"})

    def do_POST(self):
        if urlparse(self.path).path != "/expenses":
            return self._send(404, {"error": "not_found"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            row = STORE.create_expense(body)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return self._send(400, {"error": str(exc)})
        return self._send(201, row)

    def do_DELETE(self):
        match = re.fullmatch(r"/expenses/(\d+)", urlparse(self.path).path)
        if not match:
            return self._send(404, {"error": "not_found"})
        if not STORE.delete_expense(int(match.group(1))):
            return self._send(404, {"error": "not_found"})
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()


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
