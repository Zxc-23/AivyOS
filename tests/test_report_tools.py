"""AIVY-REPORT-001 Task1 报告工具单测（10 条）。"""
from __future__ import annotations
import json
import os
import tempfile
import unittest
from pathlib import Path

from aivyos_core.workbench.report_tools import (
    unified_diff_str,
    file_metadata,
    parse_unittest_output,
    parse_tsc_output,
    config_json_diff,
    mask_secrets_in_dict,
)


class TestUnifiedDiff(unittest.TestCase):
    def test_diff_modified_file_returns_hunks(self):
        old = "line1\nline2\nline3\nline4\n"
        new = "line1\nline2MOD\nline3\nline4NEW\n"
        diff = unified_diff_str(old, new, fromfile="a.py", tofile="a.py")
        self.assertIn("@@", diff)
        self.assertIn("-line2", diff)
        self.assertIn("+line2MOD", diff)

    def test_diff_identical_returns_empty_string(self):
        text = "a\nb\nc\n"
        self.assertEqual(unified_diff_str(text, text, "a", "a"), "")

    def test_diff_new_file_old_empty_has_all_added(self):
        diff = unified_diff_str("", "x=1\ny=2\n", fromfile="/dev/null", tofile="new.py")
        self.assertIn("+x=1", diff)


class TestFileMetadata(unittest.TestCase):
    def test_new_file_flags_correctly(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "hello.txt"
            p.write_text("line1\nline2\n", encoding="utf-8", newline='')
            meta = file_metadata(str(p), before_paths=set())
            self.assertEqual(meta["status"], "new")
            self.assertEqual(meta["bytes"], 12)
            self.assertEqual(meta["lines"], 2)

    def test_modified_file_flags_correctly(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.py"
            p.write_text("x=1\n", encoding="utf-8", newline='')
            before = {str(p.relative_to(tmp))}
            meta = file_metadata(str(p), before_paths=before, cwd=tmp)
            self.assertEqual(meta["status"], "modified")


class TestOutputParsers(unittest.TestCase):
    def test_parse_unittest_ran_545_pass_543(self):
        sample = ("........................................................................\n"
                  "........................................................................\n"
                  "Ran 545 tests in 65.765s\n"
                  "\n"
                  "FAILED (failures=1, errors=1)\n"
                  "\n"
                  "======================================================================\n"
                  "FAIL: test_ptt_start_stop_empty (tests.test_continuous_voice.TestPTT)\n"
                  "KeyError: 'error' at tests/test_continuous_voice.py:128\n")
        r = parse_unittest_output(sample, exit_code=1)
        self.assertEqual(r["total"], 545)
        self.assertEqual(r["ok"], 543)
        self.assertEqual(r["failures"], 1)
        self.assertEqual(r["errors"], 1)
        self.assertEqual(r["exit_code"], 1)
        self.assertIn("test_ptt_start_stop_empty", r["fail_summary"][0]["test"])

    def test_parse_unittest_all_ok_fallback_000(self):
        self.assertEqual(parse_unittest_output("", exit_code=0)["total"], 0)

    def test_parse_tsc_2_errors(self):
        sample = (
            "src/App.tsx(4711,23): error TS2322: Type 'string' is not assignable to type 'number'.\n"
            "src/chat.ts(1358,5): error TS2304: Cannot find name 'Foo'.\n"
        )
        r = parse_tsc_output(sample, exit_code=2)
        self.assertEqual(r["error_count"], 2)
        self.assertEqual(r["exit_code"], 2)
        self.assertEqual(len(r["items"]), 2)
        self.assertEqual(r["items"][0]["file"], "src/App.tsx")


class TestConfigDiff(unittest.TestCase):
    def test_config_field_level_diff_detects_manual_override(self):
        before = {"workbench": {"manual_override": {"claude_enabled": False}},
                  "agents": {"claude": {"manual": None}}}
        after = {"workbench": {"manual_override": {"claude_enabled": True}},
                 "agents": {"claude": {"manual": {"name": "Ollama"}}}}
        changes = config_json_diff(before, after)
        paths = {c["path"] for c in changes}
        self.assertIn("workbench.manual_override.claude_enabled", paths)
        self.assertIn("agents.claude.manual.name", paths)

    def test_mask_secrets_hides_middle(self):
        d = {"api_key": "sk-abcdefgh1234567890", "name": "ok"}
        masked = mask_secrets_in_dict(d)
        self.assertTrue(masked["api_key"].startswith("sk"))
        self.assertTrue(masked["api_key"].endswith("90"))
        self.assertIn("***", masked["api_key"])
        self.assertEqual(masked["name"], "ok")


if __name__ == "__main__":
    unittest.main()
