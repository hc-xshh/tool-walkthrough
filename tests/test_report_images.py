"""Pixel-level tests for build-report.py: redaction, inlining, figure numbers.

These run without Chrome — the PDF step is the only part that needs it, and it
is not exercised here. Pillow is a harness dependency; without it the pixel
assertions are skipped rather than silently passing.
"""
import base64
import importlib.util
import io
import pathlib
import re
import sys
import tempfile
import unittest

import support

try:
    from PIL import Image
    HAVE_PIL = True
except ImportError:  # pragma: no cover
    HAVE_PIL = False

_spec = importlib.util.spec_from_file_location(
    "build_report", support.ROOT / "harness" / "build-report.py")
build_report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_report)

RED = (255, 0, 0)
WHITE = (255, 255, 255)


def png_bytes(size=(40, 30), block=(8, 6, 12, 10)):
    """White canvas with a red block at (x, y, w, h)."""
    im = Image.new("RGB", size, WHITE)
    x, y, w, h = block
    for dx in range(w):
        for dy in range(h):
            im.putpixel((x + dx, y + dy), RED)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def load(data):
    return Image.open(io.BytesIO(data)).convert("RGB")


def px(im, x, y):
    return im.getpixel((x, y))


@unittest.skipUnless(HAVE_PIL, "Pillow is not installed")
class ImagePayloadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.tmp.name) / "shot.png"
        self.path.write_bytes(png_bytes())

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_rects_returns_the_original_bytes(self):
        data = self.path.read_bytes()
        self.assertEqual(build_report.image_payload(self.path), data)

    def test_rect_is_painted_white(self):
        out = build_report.image_payload(self.path, [(8, 6, 12, 10)])
        im = load(out)
        self.assertEqual(px(im, 10, 8), WHITE)   # inside the block
        self.assertEqual(px(im, 19, 15), WHITE)  # bottom-right of the block

    def test_pixels_outside_the_rect_are_untouched(self):
        out = build_report.image_payload(self.path, [(8, 6, 4, 4)])
        im = load(out)
        self.assertEqual(px(im, 15, 10), RED)    # right of the rect
        self.assertEqual(px(im, 5, 5), WHITE)    # background elsewhere

    def test_multiple_rects_all_apply(self):
        out = build_report.image_payload(self.path, [(8, 6, 3, 3), (15, 12, 3, 3)])
        im = load(out)
        self.assertEqual(px(im, 9, 7), WHITE)
        self.assertEqual(px(im, 16, 13), WHITE)

    def test_rect_past_the_edge_does_not_crash_and_keeps_the_size(self):
        original = load(self.path.read_bytes())
        out = build_report.image_payload(self.path, [(30, 20, 100, 100)])
        im = load(out)
        self.assertEqual(im.size, original.size)
        self.assertEqual(px(im, 39, 29), WHITE)  # clipped to the image

    def test_output_is_png_even_for_a_jpeg_source(self):
        jpg = pathlib.Path(self.tmp.name) / "shot.jpg"
        Image.open(io.BytesIO(png_bytes())).save(jpg, "JPEG")
        out = build_report.image_payload(jpg, [(8, 6, 4, 4)])
        self.assertTrue(out.startswith(b"\x89PNG"), "redacted output must stay lossless")


class RedactionsForTest(unittest.TestCase):
    def test_cli_only(self):
        self.assertEqual(build_report.redactions_for("a.png", [(1, 2, 3, 4)], {}),
                         [(1, 2, 3, 4)])

    def test_per_file_and_wildcard_are_added(self):
        caps = {"a.png": [(5, 5, 5, 5)], "*": [(9, 9, 9, 9)]}
        self.assertEqual(build_report.redactions_for("a.png", [], caps),
                         [(5, 5, 5, 5), (9, 9, 9, 9)])

    def test_null_entries_are_ignored(self):
        self.assertEqual(build_report.redactions_for("a.png", [], {"a.png": None}), [])


@unittest.skipUnless(HAVE_PIL, "Pillow is not installed")
class InlineLocalImagesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = pathlib.Path(self.tmp.name)
        (self.run / "shots").mkdir()
        (self.run / "shots" / "01.png").write_bytes(png_bytes())

    def tearDown(self):
        self.tmp.cleanup()

    def embed(self, md, **kw):
        return build_report.inline_local_images(md, self.run, **kw)

    def test_local_png_becomes_a_data_uri(self):
        out = self.embed("![图注](shots/01.png)")
        self.assertIn("data:image/png;base64,", out)
        self.assertNotIn("shots/01.png", out)

    def test_remote_and_data_uris_are_left_alone(self):
        md = "![a](https://example.com/x.png) ![b](data:image/png;base64,AAA)"
        self.assertEqual(self.embed(md), md)

    def test_missing_file_is_left_alone(self):
        md = "![a](shots/nope.png)"
        self.assertEqual(self.embed(md), md)

    def test_unsupported_extension_is_left_alone(self):
        (self.run / "shots" / "x.bmp").write_bytes(b"BM")
        md = "![a](shots/x.bmp)"
        self.assertEqual(self.embed(md), md)

    def test_cli_rect_redacts_the_inlined_pixels(self):
        out = self.embed("![x](shots/01.png)", cli_rects=[(8, 6, 12, 10)])
        b64 = re.search(r"base64,([A-Za-z0-9+/=]+)", out).group(1)
        im = load(base64.b64decode(b64))
        self.assertEqual(px(im, 10, 8), WHITE)

    def test_wildcard_caption_redaction_applies(self):
        out = self.embed("![x](shots/01.png)", caps_redact={"*": [(8, 6, 12, 10)]})
        b64 = re.search(r"base64,([A-Za-z0-9+/=]+)", out).group(1)
        self.assertEqual(px(load(base64.b64decode(b64)), 10, 8), WHITE)

    def test_unredacted_image_keeps_its_pixels(self):
        out = self.embed("![x](shots/01.png)")
        b64 = re.search(r"base64,([A-Za-z0-9+/=]+)", out).group(1)
        self.assertEqual(px(load(base64.b64decode(b64)), 10, 8), RED)


class FigureNumberingTest(unittest.TestCase):
    def test_standalone_image_becomes_a_numbered_figure(self):
        html, n = build_report.figure_standalone_images(
            '<p><img src="a.png" alt="首屏"></p>')
        self.assertEqual(n, 1)
        self.assertIn("<figure>", html)
        self.assertIn("图 1 · 首屏", html)

    def test_numbering_continues_from_start(self):
        _, n = build_report.figure_standalone_images(
            '<p><img src="a.png" alt="第二张"></p>', start=5)
        self.assertEqual(n, 6)

    def test_alt_text_is_escaped(self):
        html, _ = build_report.figure_standalone_images(
            '<p><img src="a.png" alt="a<b>&c"></p>')
        self.assertIn("a&lt;b&gt;&amp;c", html)

    def test_image_without_alt_gets_a_bare_number(self):
        html, _ = build_report.figure_standalone_images('<p><img src="a.png"></p>')
        self.assertIn("图 1<", html)

    def test_inline_image_inside_text_is_not_figured(self):
        html = "<p>说明 <img src=\"a.png\" alt=\"x\"> 后面还有字</p>"
        out, n = build_report.figure_standalone_images(html)
        self.assertEqual(out, html)
        self.assertEqual(n, 0)

    def test_two_images_numbered_in_order(self):
        html, n = build_report.figure_standalone_images(
            '<p><img src="a.png" alt="一"></p><p><img src="b.png" alt="二"></p>')
        self.assertEqual(n, 2)
        self.assertLess(html.index("图 1"), html.index("图 2"))


class RedactArgTest(unittest.TestCase):
    def test_a_malformed_rect_is_rejected_before_any_work(self):
        argv = sys.argv
        sys.argv = ["build-report.py", "runs/x", "--redact", "1,2,3"]
        try:
            with self.assertRaises(SystemExit) as ctx:
                build_report.main()
            self.assertEqual(ctx.exception.code, 2)
        finally:
            sys.argv = argv


if __name__ == "__main__":
    unittest.main()
