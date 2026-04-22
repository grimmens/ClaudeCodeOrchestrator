import os
import tempfile
import unittest
from unittest.mock import patch

from src.orchestrator.config import Config
from src.orchestrator.services.claude_md_updater import (
    ClaudeMdUpdateError,
    update_claude_md,
)

UPDATED_CONTENT = "# My Project\n\n## Updated section\nNew content here.\n"

COMPLETED_STEPS = [
    {"name": "add-auth", "title": "Add authentication", "result": "JWT auth implemented successfully"},
    {"name": "add-tests", "title": "Add tests", "result": "All tests passing"},
]


class TestUpdateClaudeMd(unittest.TestCase):
    def setUp(self):
        self.config = Config()
        self.tmp_dir = tempfile.mkdtemp()
        self.claude_md_path = os.path.join(self.tmp_dir, "CLAUDE.md")

    def _call(self, stdout=UPDATED_CONTENT, exit_code=0, stderr="", directive="Build a thing", steps=None):
        with patch(
            "src.orchestrator.services.claude_md_updater.claude_runner.run_claude",
            return_value=(exit_code, stdout, stderr),
        ) as mock_run:
            update_claude_md(
                directive=directive,
                project_root=self.tmp_dir,
                batch_number=1,
                completed_steps=steps if steps is not None else COMPLETED_STEPS,
                config=self.config,
            )
            return mock_run

    def test_success_writes_claude_output_to_file(self):
        self._call()
        with open(self.claude_md_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content, UPDATED_CONTENT)

    def test_exit_code_nonzero_raises_error_and_does_not_modify_file(self):
        original_content = "# Original\nThis should not change.\n"
        with open(self.claude_md_path, "w", encoding="utf-8") as f:
            f.write(original_content)

        with patch(
            "src.orchestrator.services.claude_md_updater.claude_runner.run_claude",
            return_value=(1, "", "rate limit exceeded"),
        ):
            with self.assertRaises(ClaudeMdUpdateError) as ctx:
                update_claude_md(
                    directive="Build it",
                    project_root=self.tmp_dir,
                    batch_number=1,
                    completed_steps=COMPLETED_STEPS,
                    config=self.config,
                )

        err = ctx.exception
        self.assertEqual(err.exit_code, 1)
        self.assertIn("rate limit", err.stderr)

        with open(self.claude_md_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content, original_content)

    def test_nonexistent_claude_md_uses_fallback_message_and_creates_file(self):
        self.assertFalse(os.path.exists(self.claude_md_path))

        with patch(
            "src.orchestrator.services.claude_md_updater.claude_runner.run_claude",
            return_value=(0, UPDATED_CONTENT, ""),
        ) as mock_run:
            update_claude_md(
                directive="Build it",
                project_root=self.tmp_dir,
                batch_number=1,
                completed_steps=COMPLETED_STEPS,
                config=self.config,
            )
            prompt_sent = mock_run.call_args[0][0]
            self.assertIn("File does not exist yet", prompt_sent)

        self.assertTrue(os.path.exists(self.claude_md_path))
        with open(self.claude_md_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content, UPDATED_CONTENT)

    def test_existing_claude_md_content_included_in_prompt(self):
        with open(self.claude_md_path, "w", encoding="utf-8") as f:
            f.write("# Existing docs\nSome content.\n")

        with patch(
            "src.orchestrator.services.claude_md_updater.claude_runner.run_claude",
            return_value=(0, UPDATED_CONTENT, ""),
        ) as mock_run:
            update_claude_md(
                directive="Build it",
                project_root=self.tmp_dir,
                batch_number=2,
                completed_steps=COMPLETED_STEPS,
                config=self.config,
            )
            prompt_sent = mock_run.call_args[0][0]
            self.assertIn("# Existing docs", prompt_sent)
            self.assertIn("Batch 2", prompt_sent)

    def test_completed_steps_included_in_prompt(self):
        with patch(
            "src.orchestrator.services.claude_md_updater.claude_runner.run_claude",
            return_value=(0, UPDATED_CONTENT, ""),
        ) as mock_run:
            update_claude_md(
                directive="Build it",
                project_root=self.tmp_dir,
                batch_number=1,
                completed_steps=COMPLETED_STEPS,
                config=self.config,
            )
            prompt_sent = mock_run.call_args[0][0]
            self.assertIn("Add authentication", prompt_sent)
            self.assertIn("JWT auth implemented", prompt_sent)

    def test_on_log_called_on_success(self):
        log_messages = []
        with patch(
            "src.orchestrator.services.claude_md_updater.claude_runner.run_claude",
            return_value=(0, UPDATED_CONTENT, ""),
        ):
            update_claude_md(
                directive="Build it",
                project_root=self.tmp_dir,
                batch_number=3,
                completed_steps=COMPLETED_STEPS,
                config=self.config,
                on_log=log_messages.append,
            )
        self.assertEqual(len(log_messages), 1)
        self.assertIn("3", log_messages[0])

    def test_on_log_called_on_failure(self):
        log_messages = []
        with patch(
            "src.orchestrator.services.claude_md_updater.claude_runner.run_claude",
            return_value=(1, "", "some error"),
        ):
            with self.assertRaises(ClaudeMdUpdateError):
                update_claude_md(
                    directive="Build it",
                    project_root=self.tmp_dir,
                    batch_number=1,
                    completed_steps=COMPLETED_STEPS,
                    config=self.config,
                    on_log=log_messages.append,
                )
        self.assertEqual(len(log_messages), 1)
        self.assertIn("failed", log_messages[0].lower())

    def test_claude_md_update_error_attributes(self):
        err = ClaudeMdUpdateError(42, "some error message")
        self.assertEqual(err.exit_code, 42)
        self.assertEqual(err.stderr, "some error message")


if __name__ == "__main__":
    unittest.main()
