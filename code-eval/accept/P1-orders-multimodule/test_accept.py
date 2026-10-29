"""P1 隐藏验收：取消订单跨模块一致性、并发、审计和旧库迁移。"""

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
from concurrent.futures import ThreadPoolExecutor
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
        req = urllib.request.Request(
            self.base + path, data=b"{}", method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())


class OrdersAccept(unittest.TestCase):
    def setUp(self):
        self.server = Server()

    def tearDown(self):
        self.server.close()

    def test_cancel_paid_order_updates_status_and_inventory(self):
        code, body = self.server.post("/orders/O-1001/cancel")
        self.assertEqual(code, 200, body)
        self.assertEqual(body["status"], "cancelled")
        order = self.server.get("/orders/O-1001")
        self.assertEqual(order["status"], "cancelled")
        self.assertTrue(order["cancelled_at"])
        self.assertEqual(self.server.get("/inventory/A")["reserved"], 1)
        self.assertEqual(self.server.get("/inventory/B")["reserved"], 0)

    def test_cancel_is_idempotent_and_audits_once(self):
        first = self.server.post("/orders/O-1001/cancel")
        second = self.server.post("/orders/O-1001/cancel")
        self.assertEqual((first[0], second[0]), (200, 200), (first, second))
        self.assertEqual(first[1]["status"], "cancelled")
        self.assertEqual(self.server.get("/inventory/A")["reserved"], 1)
        events = self.server.get("/audit?order_id=O-1001")["events"]
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["event"], "order_cancelled")

    def test_cancel_unknown_is_404(self):
        code, body = self.server.post("/orders/O-9999/cancel")
        self.assertEqual(code, 404, body)

    def test_cancel_shipped_is_409(self):
        code, body = self.server.post("/orders/O-1002/cancel")
        self.assertEqual(code, 409, body)
        self.assertEqual(self.server.get("/inventory/A")["reserved"], 3)

    def test_concurrent_cancel_releases_once(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.server.post("/orders/O-1001/cancel"), range(4)))
        self.assertTrue(all(code == 200 for code, _ in results), results)
        self.assertEqual(self.server.get("/inventory/A")["reserved"], 1)
        self.assertEqual(self.server.get("/inventory/B")["reserved"], 0)
        self.assertEqual(len(self.server.get("/audit?order_id=O-1001")["events"]), 1)

    def test_daily_report_excludes_cancelled(self):
        before = self.server.get("/reports/daily?date=2026-10-28")
        self.assertEqual((before["orders"], before["revenue_cents"]), (2, 1500))
        self.server.post("/orders/O-1001/cancel")
        after = self.server.get("/reports/daily?date=2026-10-28")
        self.assertEqual(after["orders"], 1)
        self.assertEqual(after["revenue_cents"], 300)
        self.assertEqual(after["cancelled_orders"], 1)

    def test_other_order_inventory_untouched(self):
        self.server.post("/orders/O-1001/cancel")
        self.assertEqual(self.server.get("/inventory/A")["reserved"], 1)
        order = self.server.get("/orders/O-1002")
        self.assertEqual(order["status"], "shipped")
        self.assertEqual(order["total_cents"], 300)

    def test_order_contract_preserved(self):
        order = self.server.get("/orders/O-1001")
        for key in ("id", "customer", "status", "total_cents", "created_at", "items"):
            self.assertIn(key, order)
        self.assertEqual(len(order["items"]), 2)
        self.assertEqual(order["items"][0]["qty"] + order["items"][1]["qty"], 3)

    def test_legacy_database_migrates_without_data_loss(self):
        order = self.server.get("/orders/O-1001")
        self.assertEqual(order["id"], "O-1001")
        self.assertIn("cancelled_at", order)
        self.assertIsNone(order["cancelled_at"])

    def test_audit_endpoint_returns_event_after_cancel(self):
        self.server.post("/orders/O-1001/cancel")
        events = self.server.get("/audit?order_id=O-1001")["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["order_id"], "O-1001")
