"""库存预占服务：HTTP 入口。"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import store


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # 测试里不要刷屏
        pass

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"ok": True})
        if self.path.startswith("/stock/"):
            sku = self.path[len("/stock/"):]
            return self._send(200, store.stock(sku))
        return self._send(404, {"error": "not_found"})

    def do_POST(self):
        if self.path != "/reserve":
            return self._send(404, {"error": "not_found"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, TypeError):
            return self._send(400, {"error": "invalid_json"})
        try:
            result = store.reserve(body)
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})
        except store.InsufficientStock:
            return self._send(409, {"error": "insufficient_stock"})
        except Exception:
            return self._send(500, {"error": "internal_error"})
        return self._send(201, result)


def make_server(host, port, data_dir):
    store.configure(data_dir)
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
