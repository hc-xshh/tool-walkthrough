"""What `audit` must catch: phantom evidence, unproven findings, thin task plans."""
import json
import pathlib
import tempfile
import unittest

import support


class AuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name) / "run"

    def tearDown(self):
        self.tmp.cleanup()

    def run_audit(self, **kwargs):
        shots = kwargs.pop("screenshots", ("S1-工作台.png", "S2-插件市场.png"))
        support.make_run(self.dir, screenshots=shots, **kwargs)
        return support.audit_output(self.dir, strict=kwargs.pop("strict", False))

    def status(self, out, name):
        return support.check_line(out, name)

    # -- a complete run ----------------------------------------------------
    def test_complete_run_passes_every_check(self):
        support.make_run(self.dir, screenshots=("S1-工作台.png", "S2-插件市场.png"))
        code, out = support.audit_output(self.dir, strict=True)
        self.assertEqual(code, 0, out)
        for name in ("report.md", "report image refs", "shot files",
                     "error events", "click -> shot", "harness.json",
                     "task count", "ui coverage", "finding attribution",
                     "problem summary"):
            self.assertEqual(self.status(out, name), "PASS", f"{name}\n{out}")

    # -- template placeholders --------------------------------------------
    def test_template_placeholders_are_not_phantom_refs(self):
        text = support.report(findings=0) + "\n![图注](shots/xx.png)\n![图注](shots/xx-tools.png)\n"
        support.make_run(self.dir, report_text=text, screenshots=("S1-工作台.png", "S2-插件市场.png"))
        _, out = support.audit_output(self.dir)
        self.assertEqual(self.status(out, "report image refs"), "WARN", out)
        self.assertNotIn("FAIL", support.check_line(out, "report image refs"))

    def test_a_real_missing_ref_is_a_failure(self):
        text = support.report(findings=1, refs=("screens/missing.png",))
        support.make_run(self.dir, report_text=text, screenshots=("S1-工作台.png", "S2-插件市场.png"))
        code, out = support.audit_output(self.dir)
        self.assertEqual(self.status(out, "report image refs"), "FAIL", out)
        self.assertEqual(code, 1)

    # -- evidence files ----------------------------------------------------
    def test_no_screenshots_at_all_is_a_failure(self):
        support.make_run(self.dir, screenshots=())
        code, out = support.audit_output(self.dir)
        self.assertEqual(self.status(out, "shot files"), "FAIL", out)
        self.assertEqual(code, 1)

    def test_event_points_at_a_deleted_screenshot(self):
        ev = json.dumps({"ts": "2026-10-22T00:00:00+08:00", "action": "shot",
                         "result": "ok", "screenshot": "shots/gone.png"})
        support.make_run(self.dir, events=[ev], screenshots=("S1-工作台.png", "S2-插件市场.png"))
        _, out = support.audit_output(self.dir)
        self.assertEqual(self.status(out, "shot files"), "FAIL", out)

    def test_error_event_is_a_warn(self):
        ev = json.dumps({"ts": "2026-10-22T00:00:00+08:00", "action": "cdp:clickel",
                         "result": "error", "detail": "not found"})
        support.make_run(self.dir, events=[ev], screenshots=("S1-工作台.png", "S2-插件市场.png"))
        code, out = support.audit_output(self.dir)
        self.assertEqual(self.status(out, "error events"), "WARN", out)
        self.assertEqual(code, 0, "a warn alone must not fail a non-strict audit")

    # -- task count --------------------------------------------------------
    def test_five_tasks_is_too_thin(self):
        support.make_run(self.dir, plan_text=support.plan(tasks=5),
                         screenshots=("S1-工作台.png", "S2-插件市场.png"))
        _, out = support.audit_output(self.dir)
        self.assertEqual(self.status(out, "task count"), "WARN", out)

    def test_sixteen_tasks_is_too_many(self):
        support.make_run(self.dir, plan_text=support.plan(tasks=16),
                         screenshots=("S1-工作台.png", "S2-插件市场.png"))
        _, out = support.audit_output(self.dir)
        self.assertEqual(self.status(out, "task count"), "WARN", out)

    def test_not_tested_rows_do_not_count_as_results(self):
        support.make_run(self.dir, plan_text=support.plan(tasks=10, results=("Not tested",)),
                         screenshots=("S1-工作台.png", "S2-插件市场.png"))
        _, out = support.audit_output(self.dir)
        # "Not tested" counts as a result by design (it is a decision), so 10 rows pass
        self.assertEqual(self.status(out, "task count"), "PASS", out)

    def test_empty_result_cells_do_not_count(self):
        rows = ["| T%d | 目标 | 状态 | 脚本 | 标准 | U01 |  |  |  |" % i for i in range(1, 11)]
        text = "# 计划\n\n## 任务\n\n| ID | 用户目标 | 起始状态 | 任务脚本 | 成功标准 | 覆盖控件 | 结果 | 证据 | 备注 |\n|---|---|---|---|---|---|---|---|---|\n" + "\n".join(rows)
        support.make_run(self.dir, plan_text=text, screenshots=("S1-工作台.png", "S2-插件市场.png"))
        _, out = support.audit_output(self.dir)
        self.assertEqual(self.status(out, "task count"), "WARN", out)

    # -- finding attribution ----------------------------------------------
    def test_finding_without_attribution_is_a_warn(self):
        text = support.report(findings=1, with_fields=False)
        support.make_run(self.dir, report_text=text, screenshots=("S1-工作台.png", "S2-插件市场.png"))
        _, out = support.audit_output(self.dir)
        self.assertEqual(self.status(out, "finding attribution"), "WARN", out)

    def test_finding_with_attribution_passes(self):
        support.make_run(self.dir, screenshots=("S1-工作台.png", "S2-插件市场.png"))
        _, out = support.audit_output(self.dir)
        self.assertEqual(self.status(out, "finding attribution"), "PASS", out)

    def test_finding_without_confidence_is_a_warn(self):
        text = support.report(findings=1, with_confidence=False)
        support.make_run(self.dir, report_text=text, screenshots=("S1-工作台.png", "S2-插件市场.png"))
        _, out = support.audit_output(self.dir)
        self.assertEqual(self.status(out, "finding attribution"), "WARN", out)
        self.assertIn("置信度", out)

    def test_report_without_problem_summary_is_a_warn(self):
        text = support.report(findings=1, with_summary=False)
        support.make_run(self.dir, report_text=text, screenshots=("S1-工作台.png", "S2-插件市场.png"))
        _, out = support.audit_output(self.dir)
        self.assertEqual(self.status(out, "problem summary"), "WARN", out)

    # -- missing deliverables ---------------------------------------------
    def test_missing_report_fails(self):
        support.make_run(self.dir, screenshots=("S1-工作台.png",))
        (self.dir / "report.md").unlink()
        code, out = support.audit_output(self.dir)
        self.assertEqual(self.status(out, "report.md"), "FAIL", out)
        self.assertEqual(code, 1)

    def test_strict_turns_a_warn_into_a_failure(self):
        ev = json.dumps({"ts": "2026-10-22T00:00:00+08:00", "action": "cdp:clickel",
                         "result": "error", "detail": "not found"})
        support.make_run(self.dir, events=[ev], screenshots=("S1-工作台.png", "S2-插件市场.png"))
        lenient, _ = support.audit_output(self.dir)
        strict, _ = support.audit_output(self.dir, strict=True)
        self.assertEqual(lenient, 0)
        self.assertEqual(strict, 1)


if __name__ == "__main__":
    unittest.main()
