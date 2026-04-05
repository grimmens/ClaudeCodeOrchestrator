"""Writes plan history files to the project root so executing agents can read them on demand."""

import json
import os
from typing import Optional

from ..database import Database

HISTORY_FILENAME = ".orchestrator-history.json"

CLAUDE_MD_MARKER_START = "\n\n<!-- ORCHESTRATOR-HISTORY-HINT-START -->"
CLAUDE_MD_MARKER_END = "<!-- ORCHESTRATOR-HISTORY-HINT-END -->"

CLAUDE_MD_HINT = (
    CLAUDE_MD_MARKER_START + "\n"
    "## Plan History\n"
    "This project has execution history from the orchestrator.\n"
    "Read the file `.orchestrator-history.json` in this directory for full plan history.\n"
    "It contains previous plan snapshots with step results that may help you understand context.\n"
    "Do NOT commit `.orchestrator-history.json` — it is a temporary file.\n"
    + CLAUDE_MD_MARKER_END + "\n"
)

# Track whether we created the CLAUDE.md file (vs appended to existing)
_created_claude_md: dict[str, bool] = {}


def write_history_file(db: Database, plan_id: str, project_root: str) -> None:
    """Write .orchestrator-history.json to the project root with plan info and snapshots."""
    plan = db.get_plan(plan_id)
    if not plan:
        return

    steps = db.get_steps_for_plan(plan_id)
    snapshots = db.get_full_lineage_history(plan_id)

    data = {
        "plan": {
            "id": plan.id,
            "name": plan.name,
            "parent_plan_id": plan.parent_plan_id,
            "created_at": plan.created_at,
        },
        "current_steps": [
            {
                "queue_position": s.queue_position,
                "name": s.name,
                "title": s.title,
                "status": s.status.value,
                "result": s.result,
            }
            for s in steps
        ],
        "history_snapshots": [
            {
                "id": snap.id,
                "plan_id": snap.plan_id,
                "snapshot_name": snap.snapshot_name,
                "snapshot_at": snap.snapshot_at,
                "summary": snap.summary,
                "steps": _parse_steps_json(snap.steps_json),
            }
            for snap in snapshots
        ],
    }

    path = os.path.join(project_root, HISTORY_FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def cleanup_history_file(project_root: str) -> None:
    """Remove .orchestrator-history.json from the project root."""
    path = os.path.join(project_root, HISTORY_FILENAME)
    if os.path.exists(path):
        os.remove(path)


def inject_claude_md_hint(project_root: str) -> None:
    """Append the history hint to CLAUDE.md, creating the file if needed."""
    path = os.path.join(project_root, "CLAUDE.md")

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if CLAUDE_MD_MARKER_START in content:
            return  # Already injected
        _created_claude_md[project_root] = False
        with open(path, "a", encoding="utf-8") as f:
            f.write(CLAUDE_MD_HINT)
    else:
        _created_claude_md[project_root] = True
        with open(path, "w", encoding="utf-8") as f:
            f.write("# CLAUDE.md\n" + CLAUDE_MD_HINT)


def cleanup_claude_md_hint(project_root: str) -> None:
    """Remove the appended history hint from CLAUDE.md, or delete it if we created it."""
    path = os.path.join(project_root, "CLAUDE.md")
    created_by_us = _created_claude_md.pop(project_root, False)

    if not os.path.exists(path):
        return

    if created_by_us:
        os.remove(path)
        return

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    start_idx = content.find(CLAUDE_MD_MARKER_START)
    end_idx = content.find(CLAUDE_MD_MARKER_END)
    if start_idx != -1 and end_idx != -1:
        end_idx += len(CLAUDE_MD_MARKER_END)
        # Also remove trailing newline if present
        if end_idx < len(content) and content[end_idx] == "\n":
            end_idx += 1
        content = content[:start_idx] + content[end_idx:]
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)


def _parse_steps_json(steps_json: str) -> list[dict]:
    """Parse steps JSON, returning simplified step data."""
    try:
        steps_data = json.loads(steps_json)
    except (json.JSONDecodeError, TypeError):
        return []
    return [
        {
            "name": s.get("name", ""),
            "title": s.get("title", ""),
            "status": s.get("status", ""),
            "result": s.get("result"),
        }
        for s in steps_data
    ]
