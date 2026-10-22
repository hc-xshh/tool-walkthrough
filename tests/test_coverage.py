"""What `coverage` must catch, and what it must not break on."""
import pathlib
import sys
import tempfile
import unittest

import support


class CoverageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name) / "run"

    def tearDown(self):
        self.tmp.cleanup()

    def run_with(self, *, states=None, nav=None, map_text=None,
                 screenshots=("S1-工作台.png", "S2-插件市场.png"), **kw):
        if map_text is None:
            map_text = support.ui_map(states=states, nav=nav)
        support.make_run(self.dir, map_text=map_text, screenshots=screenshots, **kw)
        return support.coverage_issues(self.dir)

    # -- the happy path ---------------------------------------------------
    def test_clean_map_has_no_issues(self):
        self.assertEqual(self.run_with(), [])

    def test_strict_passes_on_a_clean_run(self):
        support.make_run(self.dir, screenshots=("S1-工作台.png", "S2-插件市场.png"))
        code, out = support.coverage_output(self.dir, strict=True)
        self.assertEqual(code, 0, out)
        self.assertNotIn("crawl looks incomplete", out)

    # -- crashes found in the field ---------------------------------------
    def test_single_screen_run_does_not_crash(self):
        """UnboundLocalError regression: `edges` used to be set only for 2+ screens."""
        text = support.ui_map(
            screens=(("S1", "工作台"),),
            controls={"S1": [("U01", "主区", "发送", "按钮", "T1", "")]},
            states=[("S1", "默认", "打开", "到了", "T1"),
                    ("S1", "空态", "清空", "到了", "T1"),
                    ("S1", "加载中", "发消息", "到了", "T1")],
            nav=[],
        )
        issues = self.run_with(map_text=text, screenshots=("S1-工作台.png",))
        self.assertEqual(issues, [])

    def test_empty_map_does_not_crash(self):
        issues = self.run_with(map_text="# 页面地图\n", screenshots=())
        self.assertIn("no state matrix", " ".join(issues))

    # -- per-screen requirements ------------------------------------------
    def test_missing_first_visit_screenshot(self):
        issues = self.run_with(screenshots=("S2-插件市场.png",))
        self.assertTrue(any("S1 has no first-visit screenshot" in i for i in issues), issues)

    def test_screen_without_task(self):
        text = support.ui_map(
            controls={
                "S1": [("U01", "左侧栏", "插件市场", "按钮", "T1", "")],
                "S2": [("U03", "主区", "搜索插件", "输入框", "", "")],
            },
        )
        issues = self.run_with(map_text=text)
        self.assertTrue(any("no task covers this screen" in i for i in issues), issues)

    def test_section_without_s_number(self):
        text = support.ui_map(
            screens=(("工作台", "主界面"),),
            controls={"工作台": [("U01", "主区", "发送", "按钮", "T1", "")]},
            nav=[],
        )
        issues = self.run_with(map_text=text, screenshots=("S1-工作台.png",))
        self.assertTrue(any("has no S-number" in i for i in issues), issues)

    # -- navigation --------------------------------------------------------
    def test_too_few_nav_edges(self):
        issues = self.run_with(nav=[])
        self.assertTrue(any("navigation table has 0 edge" in i for i in issues), issues)

    def test_nav_edge_points_nowhere(self):
        issues = self.run_with(nav=[("S1", "U01", "S9 不存在")])
        self.assertTrue(any("has no section" in i for i in issues), issues)

    # -- first-level entries ----------------------------------------------
    def test_entry_with_bare_note_is_rejected(self):
        text = support.ui_map(
            controls={
                "S1": [("U01", "左侧栏", "插件市场", "按钮", "T1", ""),
                       ("U02", "左侧栏", "项目", "按钮", "T7", "不测")],
                "S2": [("U03", "主区", "搜索插件", "输入框", "T2", "")],
            },
        )
        issues = self.run_with(map_text=text)
        self.assertTrue(any("U02" in i and "usable reason" in i for i in issues), issues)

    def test_entry_with_a_real_reason_is_accepted(self):
        text = support.ui_map(
            controls={
                "S1": [("U01", "左侧栏", "插件市场", "按钮", "T1", ""),
                       ("U02", "左侧栏", "项目", "按钮", "T7", "展开/收起分组，不产生新屏")],
                "S2": [("U03", "主区", "搜索插件", "输入框", "T2", "")],
            },
        )
        self.assertEqual(self.run_with(map_text=text), [])

    def test_entry_reachable_from_another_screen_is_not_double_counted(self):
        """S6 re-renders the same rail; only S1 entries are judged."""
        text = support.ui_map(
            screens=(("S1", "工作台"), ("S2", "插件市场")),
            controls={
                "S1": [("U01", "左侧栏", "插件市场", "按钮", "T1", "")],
                "S2": [("U03", "左侧栏", "模板库", "按钮", "T2", ""),
                       ("U04", "主区", "搜索插件", "输入框", "T2", "")],
            },
            nav=[("S1", "U01", "S2 插件市场")],
        )
        issues = self.run_with(map_text=text)
        self.assertFalse(any("U03" in i for i in issues), issues)

    # -- state matrix ------------------------------------------------------
    def test_missing_state_matrix(self):
        issues = self.run_with(map_text=support.ui_map(include_states=False))
        joined = " ".join(issues)
        self.assertIn("no state matrix", joined)

    def test_entry_screen_needs_three_states(self):
        issues = self.run_with(states=[("S1", "默认", "打开", "到了", "T1"),
                                       ("S2", "默认", "打开", "到了", "T2")])
        self.assertTrue(any("need at least 3" in i for i in issues), issues)

    def test_three_default_rows_are_not_a_survey(self):
        issues = self.run_with(states=[("S1", "默认", "打开", "到了", "T1"),
                                       ("S1", "默认（再次）", "再打开", "到了", "T1"),
                                       ("S1", "默认（第三次）", "又打开", "到了", "T1"),
                                       ("S2", "默认", "打开", "到了", "T2")])
        self.assertTrue(any("默认-like" in i for i in issues), issues)

    def test_screen_without_state_rows(self):
        issues = self.run_with(states=[("S1", "默认", "打开", "到了", "T1"),
                                       ("S1", "空态", "清空", "到了", "T1"),
                                       ("S1", "加载中", "发消息", "到了", "T1")])
        self.assertTrue(any("S2 has no state rows" in i for i in issues), issues)

    def test_unreached_state_needs_a_reason(self):
        issues = self.run_with(states=[("S1", "默认", "打开", "到了", "T1"),
                                       ("S1", "空态", "清空", "到了", "T1"),
                                       ("S1", "失败", "断网", "没到", ""),
                                       ("S2", "默认", "打开", "到了", "T2")])
        self.assertTrue(any("without a reason" in i for i in issues), issues)

    def test_unreached_state_with_reason_is_fine(self):
        issues = self.run_with(states=[("S1", "默认", "打开", "到了", "T1"),
                                       ("S1", "空态", "清空", "到了", "T1"),
                                       ("S1", "失败", "断网", "没到", "本轮不测断网"),
                                       ("S2", "默认", "打开", "到了", "T2")])
        self.assertEqual(issues, [])

    # -- strict exit code --------------------------------------------------
    def test_strict_fails_when_the_crawl_is_incomplete(self):
        support.make_run(self.dir, screenshots=("S2-插件市场.png",))
        code, _ = support.coverage_output(self.dir, strict=True)
        self.assertEqual(code, 1)

    def test_uncovered_is_reported_and_strict_decides_the_exit_code(self):
        text = support.ui_map(
            controls={"S1": [("U01", "左侧栏", "插件市场", "按钮", "", "")],
                      "S2": [("U03", "主区", "搜索插件", "输入框", "T2", "")]},
        )
        support.make_run(self.dir, map_text=text, screenshots=("S1-工作台.png", "S2-插件市场.png"))
        code, out = support.coverage_output(self.dir)
        self.assertEqual(code, 0, "non-strict only fails on audit FAIL, not on coverage issues")
        self.assertIn("U01 has no task and no reason", out)
        strict_code, _ = support.coverage_output(self.dir, strict=True)
        self.assertEqual(strict_code, 1)


if __name__ == "__main__":
    unittest.main()
