import unittest

from src.orchestrator.database import Database
from src.orchestrator.models import Plan, PlanStep, StepStatus
from src.orchestrator.services.context_builder import (
    AGGRESSIVE_RESULT_LIMIT,
    HISTORY_MAX_CHARS,
    HISTORY_OLD_RESULT_LIMIT,
    HISTORY_RECENT_RESULT_LIMIT,
    MAX_TOTAL_CHARS,
    NORMAL_RESULT_LIMIT,
    build_context,
    build_history_context,
)


class TestBuildContext(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.plan = Plan(name="P", project_root="/p")
        self.db.create_plan(self.plan)

    def _add_step(self, pos, name="s", title="T", status=StepStatus.SUCCEEDED, result="ok"):
        step = PlanStep(plan_id=self.plan.id, queue_position=pos,
                        name=name, title=title, prompt="p",
                        status=status, result=result)
        self.db.create_step(step)
        return step

    def test_empty_when_no_prior_steps(self):
        self._add_step(0, status=StepStatus.PENDING)
        ctx = build_context(self.db, self.plan.id, current_queue_position=0)
        self.assertEqual(ctx, "")

    def test_includes_succeeded_prior_steps(self):
        self._add_step(0, name="setup", title="Setup", result="Created files")
        self._add_step(1, name="build", title="Build", status=StepStatus.PENDING)
        ctx = build_context(self.db, self.plan.id, current_queue_position=1)
        self.assertIn("Step 1 (setup): Setup", ctx)
        self.assertIn("Created files", ctx)

    def test_excludes_failed_steps(self):
        self._add_step(0, name="bad", title="Bad", status=StepStatus.FAILED, result="error")
        self._add_step(1, name="good", title="Good", result="fine")
        ctx = build_context(self.db, self.plan.id, current_queue_position=2)
        self.assertNotIn("bad", ctx)
        self.assertIn("good", ctx)

    def test_excludes_steps_at_or_after_current_position(self):
        self._add_step(0, name="prior", result="done")
        self._add_step(1, name="current", result="wip")
        self._add_step(2, name="future", result="later")
        ctx = build_context(self.db, self.plan.id, current_queue_position=1)
        self.assertIn("prior", ctx)
        self.assertNotIn("current", ctx)
        self.assertNotIn("future", ctx)

    def test_normal_truncation(self):
        long_result = "x" * (NORMAL_RESULT_LIMIT + 100)
        self._add_step(0, result=long_result)
        ctx = build_context(self.db, self.plan.id, current_queue_position=1)
        self.assertIn("... [truncated]", ctx)
        self.assertNotIn("x" * (NORMAL_RESULT_LIMIT + 1), ctx)

    def test_aggressive_truncation_when_total_too_large(self):
        # Create many steps with large results to exceed MAX_TOTAL_CHARS
        for i in range(30):
            self._add_step(i, name=f"s{i}", title=f"T{i}",
                           result="y" * NORMAL_RESULT_LIMIT)
        ctx = build_context(self.db, self.plan.id, current_queue_position=30)
        # Each result should be truncated to AGGRESSIVE_RESULT_LIMIT
        # (won't find a run of NORMAL_RESULT_LIMIT y's)
        self.assertNotIn("y" * (AGGRESSIVE_RESULT_LIMIT + 1), ctx)

    def test_no_result_shows_placeholder(self):
        self._add_step(0, result=None)
        ctx = build_context(self.db, self.plan.id, current_queue_position=1)
        self.assertIn("(no output)", ctx)

    def test_header_format(self):
        self._add_step(0, result="done")
        ctx = build_context(self.db, self.plan.id, current_queue_position=1)
        self.assertTrue(ctx.startswith("CONTEXT FROM PREVIOUS STEPS:"))
        self.assertIn("---", ctx)


class TestBuildHistoryContext(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.plan = Plan(name="Main Plan", project_root="/p")
        self.db.create_plan(self.plan)

    def _add_step(self, pos, name="s", title="T", status=StepStatus.SUCCEEDED, result="ok"):
        step = PlanStep(plan_id=self.plan.id, queue_position=pos,
                        name=name, title=title, prompt="p",
                        status=status, result=result)
        self.db.create_step(step)
        return step

    def test_empty_when_no_history(self):
        ctx = build_history_context(self.db, self.plan.id)
        self.assertEqual(ctx, "")

    def test_single_snapshot(self):
        self._add_step(0, name="setup", result="Created project")
        self.db.create_history_snapshot(self.plan.id, "First run", summary="1 succeeded, 0 failed")
        ctx = build_history_context(self.db, self.plan.id)
        self.assertIn("PLAN HISTORY:", ctx)
        self.assertIn("First run", ctx)
        self.assertIn("1 succeeded, 0 failed", ctx)
        self.assertIn("Step 1 (setup): Created project", ctx)

    def test_multiple_snapshots_recent_gets_more_space(self):
        self._add_step(0, name="s1", result="A" * 500)
        self.db.create_history_snapshot(self.plan.id, "Old run", summary="old")
        self.db.create_history_snapshot(self.plan.id, "New run", summary="new")
        ctx = build_history_context(self.db, self.plan.id)
        self.assertIn("Old run", ctx)
        self.assertIn("New run", ctx)
        # Split by snapshot delimiter and check old vs new truncation
        # Old snapshot (first) should be truncated more aggressively than new (last)
        old_section = ctx.split("New run")[0]
        new_section = ctx.split("New run")[1]
        self.assertNotIn("A" * (HISTORY_OLD_RESULT_LIMIT + 1), old_section)
        # New (most recent) should have more result chars
        self.assertIn("A" * (HISTORY_OLD_RESULT_LIMIT + 1), new_section)

    def test_lineage_history(self):
        parent = Plan(name="Parent Plan", project_root="/p")
        self.db.create_plan(parent)
        parent_step = PlanStep(plan_id=parent.id, queue_position=0, name="ps",
                               title="PT", prompt="p", status=StepStatus.SUCCEEDED, result="parent ok")
        self.db.create_step(parent_step)
        self.db.create_history_snapshot(parent.id, "Parent snapshot")

        child = Plan(name="Child Plan", project_root="/p", parent_plan_id=parent.id)
        self.db.create_plan(child)
        ctx = build_history_context(self.db, child.id)
        self.assertIn("PLAN HISTORY:", ctx)
        self.assertIn("This plan continues from: Parent Plan", ctx)
        self.assertIn("1 snapshot(s)", ctx)

    def test_truncation_with_large_history(self):
        for i in range(20):
            self._add_step(i, name=f"step{i}", result="Z" * 500)
        self.db.create_history_snapshot(self.plan.id, "Big snapshot", summary="big")
        ctx = build_history_context(self.db, self.plan.id, max_chars=500)
        self.assertLessEqual(len(ctx), 500)
        self.assertIn("... [truncated]", ctx)

    def test_no_lineage_no_snapshots_returns_empty(self):
        # Plan with no parent and no snapshots
        ctx = build_history_context(self.db, self.plan.id)
        self.assertEqual(ctx, "")

    def test_lineage_only_no_own_snapshots(self):
        parent = Plan(name="Parent", project_root="/p")
        self.db.create_plan(parent)
        self.db.create_history_snapshot(parent.id, "Parent snap")
        child = Plan(name="Child", project_root="/p", parent_plan_id=parent.id)
        self.db.create_plan(child)
        ctx = build_history_context(self.db, child.id)
        self.assertIn("This plan continues from: Parent", ctx)
        self.assertIn("1 snapshot(s)", ctx)


if __name__ == "__main__":
    unittest.main()
