"""Tests for plan history: CRUD, snapshot content, lineage, cascading deletes, auto-snapshot."""

import json
import unittest
from unittest.mock import MagicMock, patch

from src.orchestrator.config import Config
from src.orchestrator.database import Database
from src.orchestrator.models import Plan, PlanStep, StepStatus
from src.orchestrator.services.orchestrator import Orchestrator


class TestHistoryCRUD(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.plan = Plan(name="TestPlan", project_root="/tmp/proj")
        self.db.create_plan(self.plan)
        self._add_steps()

    def _add_steps(self):
        self.s1 = PlanStep(plan_id=self.plan.id, queue_position=0, name="init",
                           title="Init", prompt="initialize", status=StepStatus.SUCCEEDED,
                           result="Initialized OK")
        self.s2 = PlanStep(plan_id=self.plan.id, queue_position=1, name="build",
                           title="Build", prompt="build it", status=StepStatus.FAILED,
                           result="Build error")
        self.db.create_step(self.s1)
        self.db.create_step(self.s2)

    def test_snapshot_steps_json_contains_all_step_fields(self):
        snap = self.db.create_history_snapshot(self.plan.id, "v1", summary="test")
        steps = json.loads(snap.steps_json)
        self.assertEqual(len(steps), 2)
        # Verify all expected fields present
        for s in steps:
            for key in ("id", "plan_id", "queue_position", "name", "title",
                        "prompt", "description", "result", "status"):
                self.assertIn(key, s)

    def test_snapshot_preserves_step_results(self):
        snap = self.db.create_history_snapshot(self.plan.id, "v1")
        steps = json.loads(snap.steps_json)
        self.assertEqual(steps[0]["result"], "Initialized OK")
        self.assertEqual(steps[1]["result"], "Build error")

    def test_snapshot_preserves_step_statuses(self):
        snap = self.db.create_history_snapshot(self.plan.id, "v1")
        steps = json.loads(snap.steps_json)
        self.assertEqual(steps[0]["status"], "succeeded")
        self.assertEqual(steps[1]["status"], "failed")

    def test_multiple_snapshots_independent(self):
        """Modifying steps between snapshots gives different content."""
        self.db.create_history_snapshot(self.plan.id, "before-fix")
        # Fix the failed step
        self.s2.status = StepStatus.SUCCEEDED
        self.s2.result = "Build OK now"
        self.db.update_step(self.s2)
        self.db.create_history_snapshot(self.plan.id, "after-fix")

        history = self.db.get_history_for_plan(self.plan.id)
        self.assertEqual(len(history), 2)
        before = json.loads(history[0].steps_json)
        after = json.loads(history[1].steps_json)
        self.assertEqual(before[1]["status"], "failed")
        self.assertEqual(after[1]["status"], "succeeded")

    def test_delete_snapshot_does_not_affect_others(self):
        s1 = self.db.create_history_snapshot(self.plan.id, "keep")
        s2 = self.db.create_history_snapshot(self.plan.id, "delete-me")
        self.db.delete_history_snapshot(s2.id)
        remaining = self.db.get_history_for_plan(self.plan.id)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].snapshot_name, "keep")


class TestLineageTraversal(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")

    def _make_plan_with_snapshot(self, name, parent_id=None):
        plan = Plan(name=name, project_root="/p", parent_plan_id=parent_id)
        self.db.create_plan(plan)
        step = PlanStep(plan_id=plan.id, name="s", title="T", prompt="p",
                        status=StepStatus.SUCCEEDED, result="ok")
        self.db.create_step(step)
        self.db.create_history_snapshot(plan.id, f"{name}-snap")
        return plan

    def test_three_generation_lineage(self):
        grandparent = self._make_plan_with_snapshot("GP")
        parent = self._make_plan_with_snapshot("P", parent_id=grandparent.id)
        child = self._make_plan_with_snapshot("C", parent_id=parent.id)

        lineage = self.db.get_full_lineage_history(child.id)
        self.assertEqual(len(lineage), 3)
        names = {h.snapshot_name for h in lineage}
        self.assertEqual(names, {"GP-snap", "P-snap", "C-snap"})

    def test_lineage_sorted_by_date(self):
        p1 = Plan(name="P1", project_root="/p", created_at="2024-01-01T00:00:00")
        self.db.create_plan(p1)
        s1 = PlanStep(plan_id=p1.id, name="s", title="T", prompt="p",
                      status=StepStatus.SUCCEEDED)
        self.db.create_step(s1)

        p2 = Plan(name="P2", project_root="/p", parent_plan_id=p1.id,
                  created_at="2024-06-01T00:00:00")
        self.db.create_plan(p2)
        s2 = PlanStep(plan_id=p2.id, name="s", title="T", prompt="p",
                      status=StepStatus.SUCCEEDED)
        self.db.create_step(s2)

        self.db.create_history_snapshot(p1.id, "older")
        self.db.create_history_snapshot(p2.id, "newer")

        lineage = self.db.get_full_lineage_history(p2.id)
        self.assertEqual(lineage[0].snapshot_name, "older")
        self.assertEqual(lineage[1].snapshot_name, "newer")

    def test_no_infinite_loop_on_circular_reference(self):
        """If parent_plan_id somehow forms a cycle, traversal terminates."""
        p1 = Plan(name="A", project_root="/p")
        p2 = Plan(name="B", project_root="/p", parent_plan_id=p1.id)
        self.db.create_plan(p1)
        self.db.create_plan(p2)
        # Manually create a cycle (shouldn't happen, but test robustness)
        self.db.conn.execute("UPDATE plans SET parent_plan_id = ? WHERE id = ?",
                             (p2.id, p1.id))
        self.db.conn.commit()
        # Should not hang
        lineage = self.db.get_full_lineage_history(p1.id)
        self.assertIsInstance(lineage, list)

    def test_cascade_delete_removes_history(self):
        plan = Plan(name="P", project_root="/p")
        self.db.create_plan(plan)
        step = PlanStep(plan_id=plan.id, name="s", title="T", prompt="p",
                        status=StepStatus.SUCCEEDED)
        self.db.create_step(step)
        self.db.create_history_snapshot(plan.id, "snap")
        self.db.delete_plan(plan.id)
        self.assertEqual(self.db.get_history_for_plan(plan.id), [])


class TestAutoSnapshot(unittest.TestCase):
    """Test that the orchestrator auto-creates a snapshot after queue execution."""

    def setUp(self):
        self.db = Database(":memory:")
        self.plan = Plan(name="AutoSnapPlan", project_root="/tmp/proj")
        self.db.create_plan(self.plan)
        self.step = PlanStep(plan_id=self.plan.id, queue_position=0, name="test-step",
                             title="Test", prompt="do it", status=StepStatus.PENDING)
        self.db.create_step(self.step)

    @patch("src.orchestrator.services.orchestrator.claude_runner")
    @patch("src.orchestrator.services.orchestrator.write_history_file")
    @patch("src.orchestrator.services.orchestrator.inject_claude_md_hint")
    @patch("src.orchestrator.services.orchestrator.cleanup_history_file")
    @patch("src.orchestrator.services.orchestrator.cleanup_claude_md_hint")
    def test_auto_snapshot_created_after_queue_run(self, mock_cleanup_md, mock_cleanup_hist,
                                                    mock_inject, mock_write_hist, mock_runner):
        mock_runner.run_claude.return_value = (0, "Step output", "")
        config = Config(enable_history_tool=False)
        orch = Orchestrator(self.db, config)

        from threading import Event
        cancel = Event()
        orch.execute_queue(
            self.plan.id,
            on_step_started=MagicMock(),
            on_step_completed=MagicMock(),
            on_step_failed=MagicMock(),
            on_output=MagicMock(),
            cancel_event=cancel,
        )

        # Should have created an auto-snapshot
        history = self.db.get_history_for_plan(self.plan.id)
        self.assertEqual(len(history), 1)
        self.assertIn("Auto-snapshot", history[0].snapshot_name)
        self.assertIn("1 succeeded", history[0].summary)


if __name__ == "__main__":
    unittest.main()
