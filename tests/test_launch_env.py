"""launch_env: an agent host may export ELECTRON_RUN_AS_NODE; the child app must not inherit it."""
import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))

import wt  # noqa: E402


class LaunchEnvTest(unittest.TestCase):
    def test_strips_electron_run_as_node(self):
        env, stripped = wt.launch_env({"ELECTRON_RUN_AS_NODE": "1", "PATH": "x"})
        self.assertTrue(stripped)
        self.assertNotIn("ELECTRON_RUN_AS_NODE", env)
        self.assertEqual(env["PATH"], "x")

    def test_keeps_other_variables(self):
        env, stripped = wt.launch_env({"PATH": "x", "DISPLAY": ":0"})
        self.assertFalse(stripped)
        self.assertEqual(env, {"PATH": "x", "DISPLAY": ":0"})

    def test_does_not_mutate_the_caller_dict(self):
        base = {"ELECTRON_RUN_AS_NODE": "1"}
        wt.launch_env(base)
        self.assertEqual(base, {"ELECTRON_RUN_AS_NODE": "1"})

    def test_defaults_to_os_environ(self):
        old = os.environ.get("ELECTRON_RUN_AS_NODE")
        os.environ["ELECTRON_RUN_AS_NODE"] = "1"
        try:
            env, stripped = wt.launch_env()
            self.assertTrue(stripped)
            self.assertNotIn("ELECTRON_RUN_AS_NODE", env)
        finally:
            if old is None:
                os.environ.pop("ELECTRON_RUN_AS_NODE", None)
            else:
                os.environ["ELECTRON_RUN_AS_NODE"] = old


if __name__ == "__main__":
    unittest.main()
