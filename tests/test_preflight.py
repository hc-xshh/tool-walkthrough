"""preflight: account/quota markers must block, not become a failed run."""
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "preflight", ROOT / "code-eval" / "tools" / "preflight.py")
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


class PreflightTest(unittest.TestCase):
    def test_cursor_quota_marker(self):
        self.assertEqual(preflight.detect_marker("cursor", "You've hit your usage limit"), "quota")

    def test_qoder_model_entitlement_marker(self):
        self.assertEqual(
            preflight.detect_marker("qoder", "当前账号无法使用这个任务的模型，请先切换模型"),
            "account/model")

    def test_clean_text_is_not_blocked(self):
        self.assertIsNone(preflight.detect_marker("cursor", "General chat: hi / 你好"))


if __name__ == "__main__":
    unittest.main()
