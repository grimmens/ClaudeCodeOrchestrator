import threading
import unittest
from unittest.mock import MagicMock, patch

from src.orchestrator.config import Config
from src.orchestrator.database import Database
from src.orchestrator.services.auto_mode_orchestrator import (
    AutoModeCallbacks,
    AutoModeOrchestrator,
)
from src.orchestrator.services.step_generator import StepGenerationError

FAKE_STEPS = [
    {"name": "step-a", "title": "Step A", "prompt": "Do A", "description": "Does A"},
    {"name": "step-b", "title": "Step B", "prompt": "Do B", "description": "Does B"},
]


def _make_callbacks():
    return AutoModeCallbacks(
        on_status_change=MagicMock(),
        on_batch_started=MagicMock(),
        on_step_started=MagicMock(),
        on_step_completed=MagicMock(),
        on_step_failed=MagicMock(),
        on_retry_countdown=MagicMock(),
        on_batch_completed=MagicMock(),
        on_log=MagicMock(),
        on_session_ended=MagicMock(),
    )


class TestAutoModeOrchestrator(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.config = Config()
        self.config.auto_mode_retry_wait_seconds = 5
        self.session = self.db.create_auto_mode_session("Build a thing", "/fake/root")

    def tearDown(self):
        self.db.conn.close()

    def _make_orch(self, callbacks=None):
        if callbacks is None:
            callbacks = _make_callbacks()
        return AutoModeOrchestrator(
            session=self.session,
            db=self.db,
            config=self.config,
            callbacks=callbacks,
        )

    def _wait_for_stop(self, orch, timeout=5):
        if orch._thread:
            orch._thread.join(timeout=timeout)
        self.assertFalse(orch._thread.is_alive(), "Orchestrator thread did not stop in time")

    def test_successful_batch_increments_current_batch_and_calls_on_batch_completed(self):
        cb = _make_callbacks()
        orch = self._make_orch(cb)

        def on_batch_completed(batch_num, succeeded, failed):
            orch.stop()

        cb.on_batch_completed.side_effect = on_batch_completed

        with patch(
            "src.orchestrator.services.auto_mode_orchestrator.step_generator.generate_next_steps",
            return_value=FAKE_STEPS[:1],
        ), patch(
            "src.orchestrator.services.auto_mode_orchestrator.claude_runner.run_claude",
            return_value=(0, "step output", ""),
        ), patch(
            "src.orchestrator.services.auto_mode_orchestrator.claude_md_updater.update_claude_md",
        ):
            orch.start()
            self._wait_for_stop(orch)

        self.assertEqual(self.session.current_batch, 2)
        cb.on_batch_completed.assert_called_once_with(1, 1, 0)
        cb.on_session_ended.assert_called_once_with("stopped")

    def test_stop_between_steps_terminates_after_current_step(self):
        cb = _make_callbacks()
        orch = self._make_orch(cb)

        run_call_count = 0

        def fake_run_claude(prompt, working_dir, config):
            nonlocal run_call_count
            run_call_count += 1
            if run_call_count == 1:
                orch.stop()
            return (0, f"output {run_call_count}", "")

        with patch(
            "src.orchestrator.services.auto_mode_orchestrator.step_generator.generate_next_steps",
            return_value=FAKE_STEPS,
        ), patch(
            "src.orchestrator.services.auto_mode_orchestrator.claude_runner.run_claude",
            side_effect=fake_run_claude,
        ), patch(
            "src.orchestrator.services.auto_mode_orchestrator.claude_md_updater.update_claude_md",
        ):
            orch.start()
            self._wait_for_stop(orch)

        self.assertEqual(run_call_count, 1)
        cb.on_session_ended.assert_called_once_with("stopped")
        cb.on_batch_completed.assert_not_called()

    def test_stop_during_retry_countdown_exits_cleanly(self):
        cb = _make_callbacks()
        self.config.auto_mode_retry_wait_seconds = 60
        orch = self._make_orch(cb)

        def on_countdown(remaining):
            orch.stop()

        cb.on_retry_countdown.side_effect = on_countdown

        with patch(
            "src.orchestrator.services.auto_mode_orchestrator.step_generator.generate_next_steps",
            return_value=FAKE_STEPS[:1],
        ), patch(
            "src.orchestrator.services.auto_mode_orchestrator.claude_runner.run_claude",
            return_value=(1, "", "rate limit error"),
        ), patch(
            "src.orchestrator.services.auto_mode_orchestrator.claude_md_updater.update_claude_md",
        ), patch(
            "src.orchestrator.services.auto_mode_orchestrator.time.sleep",
        ):
            orch.start()
            self._wait_for_stop(orch)

        cb.on_session_ended.assert_called_once_with("stopped")
        cb.on_retry_countdown.assert_called()
        cb.on_step_failed.assert_called_once()

    def test_step_generation_retry_on_error_then_succeeds(self):
        cb = _make_callbacks()
        orch = self._make_orch(cb)
        self.config.auto_mode_retry_wait_seconds = 0

        generate_call_count = 0

        def fake_generate(*args, **kwargs):
            nonlocal generate_call_count
            generate_call_count += 1
            if generate_call_count == 1:
                raise StepGenerationError(1, "transient error")
            return FAKE_STEPS[:1]

        def on_batch_completed(batch_num, succeeded, failed):
            orch.stop()

        cb.on_batch_completed.side_effect = on_batch_completed

        with patch(
            "src.orchestrator.services.auto_mode_orchestrator.step_generator.generate_next_steps",
            side_effect=fake_generate,
        ), patch(
            "src.orchestrator.services.auto_mode_orchestrator.claude_runner.run_claude",
            return_value=(0, "output", ""),
        ), patch(
            "src.orchestrator.services.auto_mode_orchestrator.claude_md_updater.update_claude_md",
        ), patch(
            "src.orchestrator.services.auto_mode_orchestrator.time.sleep",
        ):
            orch.start()
            self._wait_for_stop(orch)

        self.assertEqual(generate_call_count, 2)
        cb.on_batch_completed.assert_called_once_with(1, 1, 0)

    def test_session_status_set_to_stopped_on_exit(self):
        cb = _make_callbacks()
        orch = self._make_orch(cb)

        def on_batch_completed(batch_num, succeeded, failed):
            orch.stop()

        cb.on_batch_completed.side_effect = on_batch_completed

        with patch(
            "src.orchestrator.services.auto_mode_orchestrator.step_generator.generate_next_steps",
            return_value=FAKE_STEPS[:1],
        ), patch(
            "src.orchestrator.services.auto_mode_orchestrator.claude_runner.run_claude",
            return_value=(0, "output", ""),
        ), patch(
            "src.orchestrator.services.auto_mode_orchestrator.claude_md_updater.update_claude_md",
        ):
            orch.start()
            self._wait_for_stop(orch)

        persisted = self.db.get_auto_mode_session(self.session.id)
        self.assertEqual(persisted.status, "stopped")

    def test_total_steps_executed_increments_on_success(self):
        cb = _make_callbacks()
        orch = self._make_orch(cb)

        def on_batch_completed(batch_num, succeeded, failed):
            orch.stop()

        cb.on_batch_completed.side_effect = on_batch_completed

        with patch(
            "src.orchestrator.services.auto_mode_orchestrator.step_generator.generate_next_steps",
            return_value=FAKE_STEPS,  # 2 steps
        ), patch(
            "src.orchestrator.services.auto_mode_orchestrator.claude_runner.run_claude",
            return_value=(0, "output", ""),
        ), patch(
            "src.orchestrator.services.auto_mode_orchestrator.claude_md_updater.update_claude_md",
        ):
            orch.start()
            self._wait_for_stop(orch)

        persisted = self.db.get_auto_mode_session(self.session.id)
        self.assertEqual(persisted.total_steps_executed, 2)


if __name__ == "__main__":
    unittest.main()
