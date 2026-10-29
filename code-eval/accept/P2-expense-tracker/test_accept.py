"""P2 隐藏验收：从零实现的记账应用。"""

import csv
import io
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

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)

    def close(self):
        self.stop()
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

    def delete(self, path):
        req = urllib.request.Request(self.base + path, method="DELETE")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, {}
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())


class ExpenseAccept(unittest.TestCase):
    def setUp(self):
        self.server = Server()

    def tearDown(self):
        self.server.close()

    def seed(self):
        rows = [
            {"amount_cents": 1000, "category": "餐饮", "spent_on": "2026-10-01", "note": "早餐"},
            {"amount_cents": 2500, "category": "餐饮", "spent_on": "2026-10-02", "note": "晚饭"},
            {"amount_cents": 400, "category": "交通", "spent_on": "2026-10-03"},
            {"amount_cents": 800, "category": "购物", "spent_on": "2026-09-30", "note": "上月"},
        ]
        for row in rows:
            self.assertEqual(self.server.post(row)[0], 201, row)

    def test_health(self):
        self.assertEqual(self.server.get("/health"), {"ok": True})

    def test_create_and_list_expense(self):
        code, body = self.server.post(
            {"amount_cents": 2350, "category": "餐饮", "spent_on": "2026-10-02", "note": "午饭"}
        )
        self.assertEqual(code, 201, body)
        self.assertGreater(body["id"], 0)
        self.assertEqual(body["amount_cents"], 2350)
        self.assertEqual(body["note"], "午饭")
        rows = self.server.get("/expenses")["expenses"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["category"], "餐饮")

    def test_amount_validation(self):
        for bad in (0, -1, "12", True, None):
            code, _ = self.server.post({"amount_cents": bad, "category": "餐饮", "spent_on": "2026-10-01"})
            self.assertEqual(code, 400, f"amount={bad!r}")

    def test_date_and_category_validation(self):
        cases = [
            {"amount_cents": 10, "category": "", "spent_on": "2026-10-01"},
            {"amount_cents": 10, "category": "餐饮", "spent_on": "2026/10/01"},
            {"amount_cents": 10, "category": "餐饮", "spent_on": "2026-02-30"},
        ]
        for payload in cases:
            code, _ = self.server.post(payload)
            self.assertEqual(code, 400, payload)

    def test_month_filter(self):
        self.seed()
        rows = self.server.get("/expenses?month=2026-10")["expenses"]
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["spent_on"].startswith("2026-10") for row in rows))
        rows = self.server.get("/expenses?month=2026-09")["expenses"]
        self.assertEqual(len(rows), 1)

    def test_summary_totals(self):
        self.seed()
        data = self.server.get("/summary?month=2026-10")
        self.assertEqual(data["total_cents"], 3900)
        self.assertEqual(data["month"], "2026-10")
        self.assertEqual(sum(item["count"] for item in data["by_category"]), 3)

    def test_summary_by_category_order(self):
        self.seed()
        data = self.server.get("/summary?month=2026-10")
        self.assertEqual([x["category"] for x in data["by_category"]], ["餐饮", "交通"])
        self.assertEqual(data["by_category"][0]["total_cents"], 3500)

    def test_delete_and_404(self):
        self.seed()
        row = self.server.get("/expenses?month=2026-10")["expenses"][0]
        code, _ = self.server.delete(f"/expenses/{row['id']}")
        self.assertEqual(code, 204)
        self.assertEqual(self.server.delete(f"/expenses/{row['id']}")[0], 404)
        self.assertEqual(len(self.server.get("/expenses?month=2026-10")["expenses"]), 2)

    def test_csv_export(self):
        self.seed()
        text = self.server.text("/export.csv?month=2026-10")
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0], ["id", "spent_on", "category", "amount_cents", "note"])
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row[1].startswith("2026-10") for row in rows[1:]))

    def test_restart_persistence(self):
        self.server.post({"amount_cents": 999, "category": "餐饮", "spent_on": "2026-10-05"})
        self.server.stop()
        self.server.start()
        rows = self.server.get("/expenses")["expenses"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["amount_cents"], 999)

    def test_static_frontend_shell(self):
        html = self.server.text("/")
        for token in ('id="expense-form"', 'name="amount"', 'name="category"', 'name="spent_on"', 'id="expense-list"'):
            self.assertIn(token, html)
        script = self.server.text("/app.js")
        self.assertIn("/expenses", script)
        self.assertIn("/summary", script)
        self.assertIn("/export.csv", script)
        self.assertTrue(self.server.text("/styles.css").strip())

    def test_unknown_route_404(self):
        code, _ = self.server.delete("/expenses/999999")
        self.assertEqual(code, 404)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.server.get("/nope")
        self.assertEqual(ctx.exception.code, 404)

    def test_note_defaults_to_empty(self):
        code, body = self.server.post({"amount_cents": 10, "category": "其他", "spent_on": "2026-10-05"})
        self.assertEqual(code, 201)
        self.assertEqual(body["note"], "")
