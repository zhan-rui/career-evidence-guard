from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from career_guard.cli import analyze
from career_guard.reporting import write_reports
from career_guard.snapshots import compare_snapshots, snapshot_directory


ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "examples" / "job-v1"
NEW = ROOT / "examples" / "job-v2"
CLAIMS = ROOT / "examples" / "claims.json"


class SnapshotTests(unittest.TestCase):
    def test_detects_modified_source_and_changed_passages(self) -> None:
        changes = compare_snapshots(snapshot_directory(OLD), snapshot_directory(NEW))
        change = next(item for item in changes if item.source_id == "job-posting.md")
        self.assertEqual(change.status, "modified")
        self.assertTrue(any("20 hours" in text for text in change.added_passages))
        self.assertTrue(any("40 hours" in text for text in change.removed_passages))
        self.assertGreaterEqual(len(change.changed_current_passage_ids), 2)


class FindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = analyze(OLD, NEW, CLAIMS)
        cls.by_id = {item.claim_id: item for item in cls.result.findings}

    def test_unchanged_location_is_explained_to_user(self) -> None:
        item = self.by_id["C1"]
        self.assertEqual(item.status, "unchanged")
        self.assertEqual(item.status_label, "未变化")
        self.assertEqual(item.current_value, "Hong Kong Science Park")
        self.assertIn("未变化", item.change_summary)

    def test_hours_show_old_and_new_values(self) -> None:
        item = self.by_id["C2"]
        self.assertEqual(item.status, "changed")
        self.assertEqual(item.previous_value, "40 小时/周")
        self.assertEqual(item.current_value, "20 小时/周")
        self.assertIn("40 小时/周", item.change_summary)
        self.assertIn("20 小时/周", item.change_summary)
        self.assertIn("时间", item.impact)

    def test_deadline_shows_earlier_date_and_delta(self) -> None:
        item = self.by_id["C4"]
        self.assertEqual(item.status, "changed")
        self.assertEqual(item.previous_value, "2026-10-15")
        self.assertEqual(item.current_value, "2026-10-01")
        self.assertIn("提前了 14 天", item.change_summary)
        self.assertIn("立即", item.recommended_action)

    def test_missing_salary_is_no_evidence_not_false(self) -> None:
        item = self.by_id["C5"]
        self.assertEqual(item.status, "no_evidence")
        self.assertEqual(item.status_label, "未找到证据")
        self.assertIn("不代表它一定为假", item.impact)

    def test_default_path_uses_no_network_or_llm(self) -> None:
        self.assertEqual(self.result.limits["llm_calls"], 0)
        self.assertEqual(self.result.limits["network_calls"], 0)

    def test_state_machine_reaches_done_through_legal_steps(self) -> None:
        states = [event["to"] for event in self.result.trace]
        self.assertEqual(states[-1], "done")
        self.assertIn("detecting_changes", states)
        self.assertIn("aligning_evidence", states)

    def test_unchanged_passage_has_same_content_addressed_id(self) -> None:
        old_passages = snapshot_directory(OLD)["job-posting.md"].passages
        new_passages = snapshot_directory(NEW)["job-posting.md"].passages
        old_location = next(p for p in old_passages if "Hong Kong Science Park" in p.text)
        new_location = next(p for p in new_passages if "Hong Kong Science Park" in p.text)
        self.assertEqual(old_location.passage_id, new_location.passage_id)

    def test_report_prioritises_user_result_and_action(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            markdown_path, json_path = write_reports(self.result, Path(temporary))
            self.assertTrue(markdown_path.exists())
            self.assertTrue(json_path.exists())
            report = markdown_path.read_text(encoding="utf-8")
            self.assertIn("用户结果表", report)
            self.assertIn("旧值", report)
            self.assertIn("新值", report)
            self.assertIn("提前了 14 天", report)
            self.assertIn("未找到证据", report)
            self.assertNotIn("`review_required`", report)


if __name__ == "__main__":
    unittest.main()
