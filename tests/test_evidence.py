"""evidence: screenshot size, metadata type, and no-shot cells."""
import contextlib
import csv
import io
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))

import wt  # noqa: E402

try:
    from PIL import Image
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False


class EvidenceTest(unittest.TestCase):
    def _args(self, **kw):
        base = dict(cells=None, shots=None, out=None, min_width=800, min_height=400,
                    strict=True, run_dir=None)
        base.update(kw)
        return type("A", (), base)

    def test_png_size_reads_ihdr(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "x.png"
            if HAVE_PIL:
                Image.new("RGB", (12, 34), "white").save(p)
            else:
                p.write_bytes(
                    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
                    b"\x00\x00\x00\x0c\x00\x00\x00\x22\x08\x02\x00\x00\x00"
                )
            self.assertEqual(wt.png_size(p), (12, 34))

    @unittest.skipUnless(HAVE_PIL, "Pillow not installed")
    def test_scan_flags_low_res_and_reads_type(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "shots").mkdir()
            Image.new("RGB", (800, 400), "white").save(root / "shots" / "ok.png")
            Image.new("RGB", (10, 10), "white").save(root / "shots" / "small.png")
            (root / "evidence.json").write_text(
                '{"shots/ok.png":{"type":"实机-正常","caption":"ok"},'
                '"shots/small.png":{"type":"实机-正常","caption":"small"}}',
                encoding="utf-8",
            )
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = wt.cmd_evidence(self._args(shots=str(root), strict=True))
            self.assertEqual(rc, 1)
            text = out.getvalue()
            self.assertIn("low-res", text)
            self.assertIn("实机-正常", text)

    def test_cells_empty_file_is_no_shot(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            cells = root / "cells.csv"
            with cells.open("w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["item", "tool", "file", "type", "caption"])
                w.writerow(["剩余用量", "Cursor", "", "", ""])
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = wt.cmd_evidence(self._args(cells=str(cells), strict=True))
            self.assertEqual(rc, 0)
            self.assertIn("no-shot", out.getvalue())
            self.assertIn("无独立截图", out.getvalue())


if __name__ == "__main__":
    unittest.main()
