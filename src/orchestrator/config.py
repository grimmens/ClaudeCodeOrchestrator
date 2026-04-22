import json
import os
from dataclasses import asdict, dataclass, field


ALL_TOOLS = ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]

_AUTO_MODE_STEP_GENERATION_PROMPT = (
    "Output a JSON array of step objects. Each step must have these fields: "
    "name (short identifier, snake_case), title (brief human-readable title), "
    "prompt (detailed instructions for the Claude agent to implement this step), "
    "description (one-sentence summary). Each step should represent one concrete, "
    "self-contained implementation task."
)

_AUTO_MODE_CLAUDE_MD_UPDATE_PROMPT = (
    "Review the current CLAUDE.md file and update it to reflect any architectural changes, "
    "new conventions, or important implementation details added in the most recent batch of steps. "
    "Keep the file concise and focused on information that helps future agents understand the codebase."
)

DEFAULTS = {
    "max_budget_usd": 5.0,
    "max_turns": 50,
    "allowed_tools": "Read Write Edit Bash Glob Grep",
    "claude_cli_path": "claude",
    "include_context": True,
    "include_history_context": True,
    "enable_history_tool": True,
    "db_path": "orchestrator.db",
    "permission_mode": "override",
    "build_command": "dotnet build",
    "auto_fix_build": True,
    "auto_mode_batch_size": 5,
    "auto_mode_retry_wait_seconds": 600,
    "auto_mode_step_generation_prompt": _AUTO_MODE_STEP_GENERATION_PROMPT,
    "auto_mode_claude_md_update_prompt": _AUTO_MODE_CLAUDE_MD_UPDATE_PROMPT,
}


@dataclass
class Config:
    max_budget_usd: float = 5.0
    max_turns: int = 50
    allowed_tools: str = "Read Write Edit Bash Glob Grep"
    claude_cli_path: str = "claude"
    include_context: bool = True
    include_history_context: bool = True
    enable_history_tool: bool = True
    db_path: str = "orchestrator.db"
    permission_mode: str = "override"
    build_command: str = "dotnet build"
    auto_fix_build: bool = True
    auto_mode_batch_size: int = 5
    auto_mode_retry_wait_seconds: int = 600
    auto_mode_step_generation_prompt: str = _AUTO_MODE_STEP_GENERATION_PROMPT
    auto_mode_claude_md_update_prompt: str = _AUTO_MODE_CLAUDE_MD_UPDATE_PROMPT


def load_config(path: str = "config.json") -> Config:
    if os.path.exists(path):
        with open(path, "r") as f:
            data = json.load(f)
        merged = {**DEFAULTS, **data}
        return Config(**{k: v for k, v in merged.items() if k in DEFAULTS})
    return Config()


def save_config(config: Config, path: str = "config.json") -> None:
    with open(path, "w") as f:
        json.dump(asdict(config), f, indent=2)
