import unittest

from src.orchestrator.database import Database
from src.orchestrator.models import Plan, PlanStep, StepStatus
from src.orchestrator.services.context_builder import (
    AGGRESSIVE_RESULT_LIMIT,
    MAX_TOTAL_CHARS,
    NORMAL_RESULT_LIMIT,
    build_context,
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


if __name__ == "__main__":
    unittest.main()
