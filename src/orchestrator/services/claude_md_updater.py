import os
from typing import Callable, List, Optional

from ..config import Config
from . import claude_runner


class ClaudeMdUpdateError(Exception):
    def __init__(self, exit_code: int, stderr: str):
        super().__init__(f"Claude exited with code {exit_code}: {stderr[:200]}")
        self.exit_code = exit_code
        self.stderr = stderr


def update_claude_md(
    directive: str,
    project_root: str,
    batch_number: int,
    completed_steps: List[dict],
    config: Config,
    on_log: Optional[Callable[[str], None]] = None,
) -> None:
    claude_md_path = os.path.join(project_root, "CLAUDE.md")
    if os.path.exists(claude_md_path):
        with open(claude_md_path, "r", encoding="utf-8") as f:
            existing_content = f.read()
    else:
        existing_content = "File does not exist yet"

    steps_section = _format_completed_steps(completed_steps)

    prompt = (
        f"DIRECTIVE:\n{directive}\n\n"
        f"CURRENT CLAUDE.md CONTENT:\n{existing_content}\n\n"
        f"JUST COMPLETED (Batch {batch_number}):\n{steps_section}\n\n"
        "TASK:\n"
        "Update the CLAUDE.md file to accurately reflect the current project state after these changes.\n"
        "Preserve existing sections that are still accurate.\n"
        "Add or update sections for new architecture, commands, or components that were just introduced.\n"
        "Keep it concise and practical - this file is read by future Claude Code agents.\n"
        "Write the COMPLETE updated CLAUDE.md content and nothing else.\n\n"
        f"{config.auto_mode_claude_md_update_prompt}"
    )

    exit_code, stdout, stderr = claude_runner.run_claude(
        prompt, working_dir=project_root, config=config
    )

    if exit_code != 0:
        if on_log:
            on_log(f"CLAUDE.md update failed (exit {exit_code}): {stderr[:200]}")
        raise ClaudeMdUpdateError(exit_code, stderr)

    with open(claude_md_path, "w", encoding="utf-8") as f:
        f.write(stdout)

    if on_log:
        on_log(f"CLAUDE.md updated after batch {batch_number}")


def _format_completed_steps(steps: List[dict]) -> str:
    if not steps:
        return "None"
    lines = []
    for step in steps:
        title = step.get("title") or step.get("name") or "?"
        result = step.get("result", "") or ""
        excerpt = result[:100].replace("\n", " ")
        line = f"- {title}"
        if excerpt:
            line += f": {excerpt}"
        lines.append(line)
    return "\n".join(lines)
