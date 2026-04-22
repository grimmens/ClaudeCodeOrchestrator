import os
from typing import List

from ..config import Config
from . import claude_runner
from . import json_parser


class StepGenerationError(Exception):
    def __init__(self, exit_code: int, stderr: str):
        super().__init__(f"Claude exited with code {exit_code}: {stderr[:200]}")
        self.exit_code = exit_code
        self.stderr = stderr


def generate_next_steps(
    directive: str,
    project_root: str,
    batch_number: int,
    completed_batch_summaries: List[dict],
    config: Config,
) -> List[dict]:
    claude_md_path = os.path.join(project_root, "CLAUDE.md")
    if os.path.exists(claude_md_path):
        with open(claude_md_path, "r", encoding="utf-8") as f:
            claude_md_content = f.read()
    else:
        claude_md_content = "No CLAUDE.md found"

    completed_section = _format_completed_batches(completed_batch_summaries)

    prompt = (
        f"DIRECTIVE:\n{directive}\n\n"
        f"CURRENT PROJECT STATE (CLAUDE.md):\n{claude_md_content}\n\n"
        f"COMPLETED BATCHES SO FAR:\n{completed_section}\n\n"
        "TASK:\n"
        f"Generate exactly {config.auto_mode_batch_size} concrete, self-contained implementation steps "
        "that make progress towards the directive.\n"
        "Each step must be achievable in a single Claude Code agent invocation.\n"
        'Output a JSON array with objects: {"name": "kebab-case-id", "title": "Short title", '
        '"prompt": "Detailed prompt for the agent", "description": "One-sentence description"}\n'
        "Output ONLY the JSON array, no other text.\n\n"
        f"{config.auto_mode_step_generation_prompt}"
    )

    exit_code, stdout, stderr = claude_runner.run_claude(
        prompt, working_dir=project_root, config=config
    )

    if exit_code != 0:
        raise StepGenerationError(exit_code, stderr)

    steps, _ = json_parser.extract_json_steps(stdout)

    result = []
    for step in steps:
        result.append({
            "name": step.get("name") or f"step-{len(result) + 1}",
            "title": step.get("title") or step.get("name") or f"Step {len(result) + 1}",
            "prompt": step.get("prompt") or "",
            "description": step.get("description") or "",
        })

    return result


def _format_completed_batches(summaries: List[dict]) -> str:
    if not summaries:
        return "None"
    lines = []
    for batch_summary in summaries:
        batch_num = batch_summary.get("batch", "?")
        steps = batch_summary.get("steps", [])
        lines.append(f"Batch {batch_num} ({len(steps)} steps):")
        for step in steps:
            name = step.get("name", "?")
            title = step.get("title", "")
            status = step.get("status", "?")
            excerpt = step.get("result_excerpt", "")
            line = f"  - {name}"
            if title:
                line += f" ({title})"
            line += f": {status}"
            if excerpt:
                line += f" — {excerpt}"
            lines.append(line)
    return "\n".join(lines)
