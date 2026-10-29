"""可见验收：从零实现记账应用后，这 5 条应该全过。"""

import json
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
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=10) as resp:
            return json.loads(resp.read())

    def text(self, path):
        with urllib.request.urlopen(self.base + path, timeout=10) as resp:
            return resp.read().decode("utf-8")

    def post(self, payload):
        req = urllib.request.Request(
            self.base + "/expenses", data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json"},
        )
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

    def test_create_and_list_expense(self):
        code, body = self.server.post({"amount_cents": 2350, "category": "餐饮", "spent_on": "2026-10-02", "note": "午饭"})
        self.assertEqual(code, 201, body)
        self.assertGreater(body["id"], 0)
        rows = self.server.get("/expenses")["expenses"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["amount_cents"], 2350)

    def test_validation_rejects_bad_amount(self):
        code, _ = self.server.post({"amount_cents": 0, "category": "餐饮", "spent_on": "2026-10-02"})
        self.assertEqual(code, 400)
        code, _ = self.server.post({"amount_cents": 12, "category": "餐饮", "spent_on": "10/02/2026"})
        self.assertEqual(code, 400)

    def test_summary(self):
        for payload in (
            {"amount_cents": 1000, "category": "餐饮", "spent_on": "2026-10-01"},
            {"amount_cents": 2500, "category": "餐饮", "spent_on": "2026-10-02"},
            {"amount_cents": 400, "category": "交通", "spent_on": "2026-10-03"},
        ):
            self.assertEqual(self.server.post(payload)[0], 201)
        data = self.server.get("/summary?month=2026-10")
        self.assertEqual(data["total_cents"], 3900)
        self.assertEqual(data["by_category"][0]["category"], "餐饮")
        self.assertEqual(data["by_category"][0]["total_cents"], 3500)

    def test_frontend_shell(self):
        html = self.server.text("/")
        self.assertIn('id="expense-form"', html)
        self.assertIn('name="amount"', html)
        self.assertIn('name="spent_on"', html)
        self.assertIn('src="/app.js"', html)
        script = self.server.text("/app.js")
        self.assertIn("/expenses", script)
        self.assertIn("/summary", script)
