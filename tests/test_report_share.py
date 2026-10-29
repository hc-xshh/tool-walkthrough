import base64
import io
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "harness"))
import report_share  # noqa: E402


def _png(path: Path, size=(8, 8), color=(255, 0, 0)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


class ReportShareTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _uri_bytes(self, text: str) -> bytes:
        uri = text.split("](", 1)[1].rstrip(")")
        return base64.b64decode(uri.split(",", 1)[1])

    def test_inline_images_replaces_local_png(self):
        _png(self.root / "shots" / "a.png")
        text, inlined, missing = report_share.inline_images("![a](shots/a.png)", self.root)
        self.assertEqual((inlined, missing), (1, 0))
        self.assertIn("data:image/png;base64,", text)
        self.assertNotIn("shots/a.png", text)

    def test_html_has_embedded_images_only(self):
        _png(self.root / "shots" / "a.png")
        page = report_share.md_to_html("![a](shots/a.png)", self.root, "t")
        self.assertIn("data:image/png;base64,", page)
        self.assertNotIn('src="shots/a.png"', page)

    def test_html_escapes_title(self):
        page = report_share.md_to_html("x", self.root, "<script>alert(1)</script>")
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)

    def test_thumb_falls_back_to_full_size_original(self):
        _png(self.root / "shots" / "thumbs" / "a.png", size=(8, 8))
        _png(self.root / "shots" / "full" / "a.png", size=(20, 20))
        text, _, _ = report_share.inline_images("![a](shots/thumbs/a.png)", self.root)
        self.assertEqual(Image.open(io.BytesIO(self._uri_bytes(text))).size, (20, 20))

    def test_compact_mode_resizes_and_uses_jpeg(self):
        _png(self.root / "shots" / "a.png", size=(800, 400))
        text, _, _ = report_share.inline_images("![a](shots/a.png)", self.root,
                                                mode="compact", width=200)
        self.assertIn("data:image/jpeg;base64,", text)
        self.assertEqual(Image.open(io.BytesIO(self._uri_bytes(text))).size[0], 200)


if __name__ == "__main__":
    unittest.main()
