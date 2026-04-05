import json
import os
from dataclasses import asdict, dataclass, field


ALL_TOOLS = ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]

DEFAULTS = {
    "max_budget_usd": 5.0,
    "max_turns": 50,
    "allowed_tools": "Read Write Edit Bash Glob Grep",
    "claude_cli_path": "claude",
    "include_context": True,
    "include_history_context": True,
    "db_path": "orchestrator.db",
    "permission_mode": "override",
}


@dataclass
class Config:
    max_budget_usd: float = 5.0
    max_turns: int = 50
    allowed_tools: str = "Read Write Edit Bash Glob Grep"
    claude_cli_path: str = "claude"
    include_context: bool = True
    include_history_context: bool = True
    db_path: str = "orchestrator.db"
    permission_mode: str = "override"


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
