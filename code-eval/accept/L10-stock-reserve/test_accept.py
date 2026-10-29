"""L10 隐藏验收：并发不超卖、幂等、重启持久化、入参校验。"""

import json
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
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
            [sys.executable, str(REPO / "app.py"), "--port", str(port),
             "--data", str(self.tmp / "data")],
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

    def post(self, payload):
        req = urllib.request.Request(
            self.base + "/reserve", data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw)
            except ValueError:
                return exc.code, {"raw": raw.decode("utf-8", "replace")}

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=10) as resp:
            return json.loads(resp.read())


class StockAccept(unittest.TestCase):
    def setUp(self):
        self.server = Server()

    def tearDown(self):
        self.server.close()

    def test_basic_reserve_and_stock(self):
        code, body = self.server.post({"sku": "A", "qty": 3, "request_id": "r-basic"})
        self.assertEqual(code, 201, body)
        self.assertEqual(body["qty"], 3)
        stock = self.server.get("/stock/A")
        self.assertEqual((stock["available"], stock["reserved"]), (7, 3), stock)

    def test_insufficient_stock_is_409(self):
        code, body = self.server.post({"sku": "B", "qty": 6, "request_id": "r-over"})
        self.assertEqual(code, 409, body)
        self.assertEqual(body.get("error"), "insufficient_stock", body)
        self.assertEqual(self.server.get("/stock/B")["available"], 5)

    def test_invalid_payload_is_400(self):
        cases = [
            {"sku": "A", "qty": 0, "request_id": "r-zero"},
            {"sku": "A", "qty": -1, "request_id": "r-negative"},
            {"sku": "A", "qty": "2", "request_id": "r-string"},
            {"sku": "A", "qty": True, "request_id": "r-bool"},
            {"sku": "A", "qty": 1},
            {"qty": 1, "request_id": "r-nosku"},
            [],
            "x",
            1,
        ]
        for payload in cases:
            code, body = self.server.post(payload)
            self.assertEqual(code, 400, f"{payload} -> {code} {body}")
        self.assertEqual(self.server.get("/stock/A")["available"], 10)

    def test_concurrent_requests_do_not_oversell(self):
        barrier = threading.Barrier(12)

        def reserve(i):
            barrier.wait(timeout=10)
            return self.server.post({"sku": "A", "qty": 1, "request_id": f"r-c{i}"})

        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(reserve, range(12)))
        codes = [c for c, _ in results]
        self.assertEqual(codes.count(201), 10, results)
        self.assertEqual(codes.count(409), 2, results)
        stock = self.server.get("/stock/A")
        self.assertEqual(stock["available"], 0, stock)
        self.assertEqual(stock["reserved"], 10, stock)

    def test_duplicate_request_id_returns_same_reservation(self):
        first = self.server.post({"sku": "A", "qty": 2, "request_id": "r-dup"})
        second = self.server.post({"sku": "A", "qty": 2, "request_id": "r-dup"})
        self.assertEqual(first[0], 201, first)
        self.assertEqual(second[0], 201, second)
        self.assertEqual(first[1]["reservation_id"], second[1]["reservation_id"], (first, second))
        self.assertEqual(self.server.get("/stock/A")["available"], 8)

    def test_concurrent_duplicate_charges_once(self):
        barrier = threading.Barrier(8)

        def same(_):
            barrier.wait(timeout=10)
            return self.server.post({"sku": "B", "qty": 1, "request_id": "r-same"})

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(same, range(8)))
        self.assertTrue(all(code == 201 for code, _ in results), results)
        ids = {body["reservation_id"] for _, body in results}
        self.assertEqual(len(ids), 1, results)
        self.assertEqual(self.server.get("/stock/B")["available"], 4)

    def test_restart_keeps_reservations_and_idempotency(self):
        code, first = self.server.post({"sku": "A", "qty": 4, "request_id": "r-restart"})
        self.assertEqual(code, 201, first)
        self.server.stop()
        self.server.start()
        stock = self.server.get("/stock/A")
        self.assertEqual((stock["available"], stock["reserved"]), (6, 4), stock)
        code, again = self.server.post({"sku": "A", "qty": 4, "request_id": "r-restart"})
        self.assertEqual(code, 201, again)
        self.assertEqual(again["reservation_id"], first["reservation_id"])
        self.assertEqual(self.server.get("/stock/A")["available"], 6)


if __name__ == "__main__":
    unittest.main()
