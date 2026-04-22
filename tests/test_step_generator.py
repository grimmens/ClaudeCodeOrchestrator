import json
import os
import tempfile
import unittest
from unittest.mock import patch

from src.orchestrator.config import Config
from src.orchestrator.services.step_generator import (
    StepGenerationError,
    generate_next_steps,
)

VALID_STEPS = [
    {"name": "add-auth", "title": "Add authentication", "prompt": "Implement JWT auth", "description": "Adds JWT-based auth"},
    {"name": "add-tests", "title": "Add tests", "prompt": "Write unit tests", "description": "Covers auth module"},
]

VALID_JSON = json.dumps(VALID_STEPS)
MARKDOWN_JSON = f"```json\n{VALID_JSON}\n```"


class TestGenerateNextSteps(unittest.TestCase):
    def setUp(self):
        self.config = Config()
        self.tmp_dir = tempfile.mkdtemp()

    def _call(self, stdout="[]", exit_code=0, stderr="", directive="Build a thing"):
        with patch(
            "src.orchestrator.services.step_generator.claude_runner.run_claude",
            return_value=(exit_code, stdout, stderr),
        ) as mock_run:
            result = generate_next_steps(
                directive=directive,
                project_root=self.tmp_dir,
                batch_number=1,
                completed_batch_summaries=[],
                config=self.config,
            )
            return result, mock_run

    def test_valid_json_returns_parsed_steps(self):
        result, _ = self._call(stdout=VALID_JSON)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "add-auth")
        self.assertEqual(result[0]["title"], "Add authentication")
        self.assertEqual(result[0]["prompt"], "Implement JWT auth")
        self.assertEqual(result[1]["name"], "add-tests")

    def test_markdown_wrapped_json_uses_fallback_parsing(self):
        result, _ = self._call(stdout=MARKDOWN_JSON)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "add-auth")

    def test_exit_code_nonzero_raises_step_generation_error(self):
        with self.assertRaises(StepGenerationError) as ctx:
            self._call(stdout="", exit_code=1, stderr="rate limit")
        err = ctx.exception
        self.assertEqual(err.exit_code, 1)
        self.assertIn("rate limit", err.stderr)

    def test_claude_md_included_when_file_exists(self):
        claude_md_path = os.path.join(self.tmp_dir, "CLAUDE.md")
        with open(claude_md_path, "w", encoding="utf-8") as f:
            f.write("# My Project\nThis is the project docs.")

        with patch(
            "src.orchestrator.services.step_generator.claude_runner.run_claude",
            return_value=(0, VALID_JSON, ""),
        ) as mock_run:
            generate_next_steps(
                directive="Build it",
                project_root=self.tmp_dir,
                batch_number=1,
                completed_batch_summaries=[],
                config=self.config,
            )
            prompt_sent = mock_run.call_args[0][0]
            self.assertIn("# My Project", prompt_sent)
            self.assertIn("This is the project docs.", prompt_sent)

    def test_claude_md_omitted_gracefully_when_missing(self):
        with patch(
            "src.orchestrator.services.step_generator.claude_runner.run_claude",
            return_value=(0, VALID_JSON, ""),
        ) as mock_run:
            generate_next_steps(
                directive="Build it",
                project_root=self.tmp_dir,
                batch_number=1,
                completed_batch_summaries=[],
                config=self.config,
            )
            prompt_sent = mock_run.call_args[0][0]
            self.assertIn("No CLAUDE.md found", prompt_sent)

    def test_missing_title_and_description_filled_with_defaults(self):
        minimal = json.dumps([{"name": "do-thing", "prompt": "Do the thing"}])
        result, _ = self._call(stdout=minimal)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "do-thing")
        self.assertEqual(result[0]["prompt"], "Do the thing")
        self.assertIsInstance(result[0]["title"], str)
        self.assertIsInstance(result[0]["description"], str)

    def test_completed_batches_included_in_prompt(self):
        summaries = [
            {
                "batch": 1,
                "steps": [
                    {"name": "setup", "title": "Setup", "status": "succeeded", "result_excerpt": "done"},
                ],
            }
        ]
        with patch(
            "src.orchestrator.services.step_generator.claude_runner.run_claude",
            return_value=(0, VALID_JSON, ""),
        ) as mock_run:
            generate_next_steps(
                directive="Build it",
                project_root=self.tmp_dir,
                batch_number=2,
                completed_batch_summaries=summaries,
                config=self.config,
            )
            prompt_sent = mock_run.call_args[0][0]
            self.assertIn("Batch 1", prompt_sent)
            self.assertIn("setup", prompt_sent)
            self.assertIn("succeeded", prompt_sent)

    def test_step_generation_error_attributes(self):
        err = StepGenerationError(42, "some error message")
        self.assertEqual(err.exit_code, 42)
        self.assertEqual(err.stderr, "some error message")


if __name__ == "__main__":
    unittest.main()
