import json
import unittest

from src.orchestrator.database import Database
from src.orchestrator.models import AgentRun, AutoModeSession, Plan, PlanHistory, PlanStep, StepStatus


class TestDatabasePlans(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")

    def test_create_and_get_plan(self):
        plan = Plan(name="Test Plan", project_root="/tmp/proj")
        self.db.create_plan(plan)
        fetched = self.db.get_plan(plan.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.name, "Test Plan")
        self.assertEqual(fetched.project_root, "/tmp/proj")

    def test_get_plans_ordered_by_date(self):
        p1 = Plan(name="First", project_root="/a", created_at="2024-01-01T00:00:00")
        p2 = Plan(name="Second", project_root="/b", created_at="2024-02-01T00:00:00")
        self.db.create_plan(p1)
        self.db.create_plan(p2)
        plans = self.db.get_plans()
        self.assertEqual(len(plans), 2)
        self.assertEqual(plans[0].name, "Second")  # newest first

    def test_update_plan(self):
        plan = Plan(name="Old Name", project_root="/old")
        self.db.create_plan(plan)
        plan.name = "New Name"
        plan.project_root = "/new"
        self.db.update_plan(plan)
        fetched = self.db.get_plan(plan.id)
        self.assertEqual(fetched.name, "New Name")
        self.assertEqual(fetched.project_root, "/new")

    def test_delete_plan_cascades_steps(self):
        plan = Plan(name="P", project_root="/p")
        self.db.create_plan(plan)
        step = PlanStep(plan_id=plan.id, name="s1", title="T", prompt="do it")
        self.db.create_step(step)
        self.db.delete_plan(plan.id)
        self.assertIsNone(self.db.get_plan(plan.id))
        self.assertEqual(self.db.get_steps_for_plan(plan.id), [])

    def test_get_nonexistent_plan(self):
        self.assertIsNone(self.db.get_plan("nonexistent"))


class TestDatabaseSteps(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.plan = Plan(name="P", project_root="/p")
        self.db.create_plan(self.plan)

    def _make_step(self, **kwargs):
        defaults = dict(plan_id=self.plan.id, name="s", title="T", prompt="p")
        defaults.update(kwargs)
        return PlanStep(**defaults)

    def test_create_and_get_step(self):
        step = self._make_step(name="step1", title="Step One")
        self.db.create_step(step)
        fetched = self.db.get_step(step.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.name, "step1")
        self.assertEqual(fetched.status, StepStatus.PENDING)

    def test_get_steps_ordered_by_position(self):
        s1 = self._make_step(name="a", queue_position=1)
        s2 = self._make_step(name="b", queue_position=0)
        self.db.create_step(s1)
        self.db.create_step(s2)
        steps = self.db.get_steps_for_plan(self.plan.id)
        self.assertEqual(steps[0].name, "b")
        self.assertEqual(steps[1].name, "a")

    def test_update_step_status(self):
        step = self._make_step()
        self.db.create_step(step)
        step.status = StepStatus.SUCCEEDED
        step.result = "All done"
        self.db.update_step(step)
        fetched = self.db.get_step(step.id)
        self.assertEqual(fetched.status, StepStatus.SUCCEEDED)
        self.assertEqual(fetched.result, "All done")

    def test_delete_step(self):
        step = self._make_step()
        self.db.create_step(step)
        self.db.delete_step(step.id)
        self.assertIsNone(self.db.get_step(step.id))

    def test_reorder_steps(self):
        s1 = self._make_step(name="first", queue_position=0)
        s2 = self._make_step(name="second", queue_position=1)
        s3 = self._make_step(name="third", queue_position=2)
        for s in (s1, s2, s3):
            self.db.create_step(s)
        # Reverse order
        self.db.reorder_steps(self.plan.id, [s3.id, s2.id, s1.id])
        steps = self.db.get_steps_for_plan(self.plan.id)
        self.assertEqual([s.name for s in steps], ["third", "second", "first"])


class TestDatabaseAgentRuns(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.plan = Plan(name="P", project_root="/p")
        self.db.create_plan(self.plan)
        self.step = PlanStep(plan_id=self.plan.id, name="s", title="T", prompt="p")
        self.db.create_step(self.step)

    def test_create_and_get_run(self):
        run = AgentRun(step_id=self.step.id, attempt_number=1, status="succeeded",
                       output="ok", exit_code=0, cost_usd=0.05)
        self.db.create_agent_run(run)
        runs = self.db.get_runs_for_step(self.step.id)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].status, "succeeded")
        self.assertEqual(runs[0].cost_usd, 0.05)

    def test_get_runs_for_plan(self):
        run = AgentRun(step_id=self.step.id, attempt_number=1, status="done",
                       started_at="2024-01-01T00:00:00")
        self.db.create_agent_run(run)
        runs = self.db.get_runs_for_plan(self.plan.id)
        self.assertEqual(len(runs), 1)

    def test_delete_runs_for_step(self):
        run = AgentRun(step_id=self.step.id, attempt_number=1, status="done")
        self.db.create_agent_run(run)
        self.db.delete_runs_for_step(self.step.id)
        self.assertEqual(self.db.get_runs_for_step(self.step.id), [])

    def test_delete_runs_for_plan(self):
        run = AgentRun(step_id=self.step.id, attempt_number=1, status="done")
        self.db.create_agent_run(run)
        self.db.delete_runs_for_plan(self.plan.id)
        self.assertEqual(self.db.get_runs_for_step(self.step.id), [])


class TestDatabasePlanHistory(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.plan = Plan(name="P", project_root="/p")
        self.db.create_plan(self.plan)
        # Add some steps
        self.step1 = PlanStep(plan_id=self.plan.id, name="s1", title="Step 1",
                              prompt="do thing 1", status=StepStatus.SUCCEEDED, result="ok")
        self.step2 = PlanStep(plan_id=self.plan.id, name="s2", title="Step 2",
                              prompt="do thing 2", queue_position=1, status=StepStatus.FAILED,
                              result="error")
        self.db.create_step(self.step1)
        self.db.create_step(self.step2)

    def test_create_and_get_snapshot(self):
        snapshot = self.db.create_history_snapshot(self.plan.id, "v1", summary="test run")
        self.assertEqual(snapshot.plan_id, self.plan.id)
        self.assertEqual(snapshot.snapshot_name, "v1")
        self.assertEqual(snapshot.summary, "test run")
        steps_data = json.loads(snapshot.steps_json)
        self.assertEqual(len(steps_data), 2)
        self.assertEqual(steps_data[0]["status"], "succeeded")
        self.assertEqual(steps_data[1]["status"], "failed")

    def test_get_history_for_plan(self):
        self.db.create_history_snapshot(self.plan.id, "snap1")
        self.db.create_history_snapshot(self.plan.id, "snap2")
        history = self.db.get_history_for_plan(self.plan.id)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].snapshot_name, "snap1")
        self.assertEqual(history[1].snapshot_name, "snap2")

    def test_delete_history_snapshot(self):
        snapshot = self.db.create_history_snapshot(self.plan.id, "to-delete")
        self.db.delete_history_snapshot(snapshot.id)
        history = self.db.get_history_for_plan(self.plan.id)
        self.assertEqual(len(history), 0)

    def test_cascade_delete_on_plan_delete(self):
        self.db.create_history_snapshot(self.plan.id, "snap")
        self.db.delete_plan(self.plan.id)
        history = self.db.get_history_for_plan(self.plan.id)
        self.assertEqual(len(history), 0)

    def test_lineage_history(self):
        # Create a parent plan with history
        parent = Plan(name="Parent", project_root="/p",
                      created_at="2024-01-01T00:00:00")
        self.db.create_plan(parent)
        parent_step = PlanStep(plan_id=parent.id, name="ps", title="PT", prompt="pp",
                               status=StepStatus.SUCCEEDED)
        self.db.create_step(parent_step)
        self.db.create_history_snapshot(parent.id, "parent-snap")

        # Create a child plan linked to parent
        child = Plan(name="Child", project_root="/p",
                     created_at="2024-02-01T00:00:00", parent_plan_id=parent.id)
        self.db.create_plan(child)
        child_step = PlanStep(plan_id=child.id, name="cs", title="CT", prompt="cp",
                              status=StepStatus.SUCCEEDED)
        self.db.create_step(child_step)
        self.db.create_history_snapshot(child.id, "child-snap")

        # Lineage from child should include both
        lineage = self.db.get_full_lineage_history(child.id)
        self.assertEqual(len(lineage), 2)
        names = [h.snapshot_name for h in lineage]
        self.assertIn("parent-snap", names)
        self.assertIn("child-snap", names)

    def test_parent_plan_id_stored_and_retrieved(self):
        child = Plan(name="Child", project_root="/c", parent_plan_id=self.plan.id)
        self.db.create_plan(child)
        fetched = self.db.get_plan(child.id)
        self.assertEqual(fetched.parent_plan_id, self.plan.id)

    def test_parent_plan_id_null_by_default(self):
        fetched = self.db.get_plan(self.plan.id)
        self.assertIsNone(fetched.parent_plan_id)


class TestAutoModeSessions(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")

    def test_create_and_get_session(self):
        session = self.db.create_auto_mode_session("Build a REST API", "/tmp/project")
        self.assertIsNotNone(session.id)
        self.assertEqual(session.directive, "Build a REST API")
        self.assertEqual(session.project_root, "/tmp/project")
        self.assertEqual(session.status, "running")
        self.assertEqual(session.current_batch, 1)
        self.assertEqual(session.total_steps_executed, 0)
        self.assertIsNone(session.last_error)

        fetched = self.db.get_auto_mode_session(session.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.directive, "Build a REST API")
        self.assertEqual(fetched.status, "running")

    def test_update_session(self):
        session = self.db.create_auto_mode_session("Refactor codebase", "/tmp/proj")
        session.status = "completed"
        session.current_batch = 3
        session.total_steps_executed = 12
        session.last_error = None
        self.db.update_auto_mode_session(session)

        fetched = self.db.get_auto_mode_session(session.id)
        self.assertEqual(fetched.status, "completed")
        self.assertEqual(fetched.current_batch, 3)
        self.assertEqual(fetched.total_steps_executed, 12)

    def test_update_session_with_error(self):
        session = self.db.create_auto_mode_session("Add tests", "/tmp/proj")
        session.status = "error"
        session.last_error = "Build failed with exit code 1"
        self.db.update_auto_mode_session(session)

        fetched = self.db.get_auto_mode_session(session.id)
        self.assertEqual(fetched.status, "error")
        self.assertEqual(fetched.last_error, "Build failed with exit code 1")

    def test_get_nonexistent_session(self):
        result = self.db.get_auto_mode_session("nonexistent-id")
        self.assertIsNone(result)

    def test_get_recent_sessions(self):
        s1 = self.db.create_auto_mode_session("Task 1", "/p1")
        s2 = self.db.create_auto_mode_session("Task 2", "/p2")
        s3 = self.db.create_auto_mode_session("Task 3", "/p3")

        sessions = self.db.get_recent_auto_mode_sessions(limit=10)
        self.assertEqual(len(sessions), 3)
        # Most recent first
        directives = [s.directive for s in sessions]
        self.assertEqual(directives[0], "Task 3")

    def test_get_recent_sessions_limit(self):
        for i in range(5):
            self.db.create_auto_mode_session(f"Task {i}", "/p")
        sessions = self.db.get_recent_auto_mode_sessions(limit=3)
        self.assertEqual(len(sessions), 3)

    def test_plan_linked_to_session(self):
        session = self.db.create_auto_mode_session("Auto directive", "/repo")
        plan = Plan(name="Batch 1", project_root="/repo")
        self.db.create_plan(plan, auto_mode_session_id=session.id)

        fetched = self.db.get_plan(plan.id)
        self.assertEqual(fetched.auto_mode_session_id, session.id)

    def test_plan_auto_mode_session_id_null_by_default(self):
        plan = Plan(name="Normal Plan", project_root="/p")
        self.db.create_plan(plan)
        fetched = self.db.get_plan(plan.id)
        self.assertIsNone(fetched.auto_mode_session_id)


if __name__ == "__main__":
    unittest.main()
