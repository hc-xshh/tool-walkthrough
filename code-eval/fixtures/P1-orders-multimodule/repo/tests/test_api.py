"""基线可见测试：订单查询、库存和日报。取消订单用例会失败，等实现后通过。"""

import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(REPO / "data", self.tmp / "data")
        self.proc = None
        self.base = None
        self.start()

    def start(self):
        port = free_port()
        self.proc = subprocess.Popen(
            [sys.executable, str(REPO / "app.py"), "--port", str(port), "--data", str(self.tmp / "data")],
            cwd=str(REPO), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.base = f"http://127.0.0.1:{port}"
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                self.get("/health")
                return
            except Exception:
                if self.proc.poll() is not None:
                    out, err = self.proc.communicate(timeout=2)
                    raise RuntimeError(f"server exited: {err[-800:] or out[-800:]}")
                time.sleep(0.05)
        raise RuntimeError("server did not become ready")

    def close(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=10) as resp:
            return json.loads(resp.read())

    def post(self, path):
        req = urllib.request.Request(self.base + path, data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())


class Smoke(unittest.TestCase):
    def setUp(self):
        self.server = Server()

    def tearDown(self):
        self.server.close()

    def test_health(self):
        self.assertEqual(self.server.get("/health"), {"ok": True})

    def test_order_contract(self):
        order = self.server.get("/orders/O-1001")
        self.assertEqual(order["status"], "paid")
        self.assertEqual(order["total_cents"], 1200)
        self.assertEqual(len(order["items"]), 2)

    def test_inventory(self):
        stock = self.server.get("/inventory/A")
        self.assertEqual((stock["total"], stock["reserved"], stock["available"]), (10, 3, 7))

    def test_daily_report(self):
        report = self.server.get("/reports/daily?date=2026-10-28")
        self.assertEqual((report["orders"], report["revenue_cents"]), (2, 1500))

    def test_cancel_paid_order(self):
        code, body = self.server.post("/orders/O-1001/cancel")
        self.assertEqual(code, 200, body)
        self.assertEqual(body["status"], "cancelled")
        self.assertEqual(self.server.get("/inventory/A")["reserved"], 1)
        self.assertEqual(self.server.get("/inventory/B")["reserved"], 0)
