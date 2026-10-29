"""可见测试：只覆盖最基本的预占与库存查询。"""

import json
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import app

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(REPO / "data", cls.tmp / "data")
        cls.httpd = app.make_server("127.0.0.1", 0, cls.tmp / "data")
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def post(self, payload):
        req = urllib.request.Request(
            self.base + "/reserve",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as resp:
            return json.loads(resp.read())

    def test_reserve_then_stock(self):
        code, body = self.post({"sku": "A", "qty": 2, "request_id": "r-1"})
        self.assertEqual(code, 201)
        self.assertEqual(body["qty"], 2)
        self.assertEqual(self.get("/stock/A")["available"], 8)

    def test_insufficient_stock(self):
        code, body = self.post({"sku": "B", "qty": 99, "request_id": "r-2"})
        self.assertEqual(code, 409)
        self.assertEqual(body["error"], "insufficient_stock")


if __name__ == "__main__":
    unittest.main()
