import json

from ..database import Database
from ..models import StepStatus

MAX_TOTAL_CHARS = 10000
NORMAL_RESULT_LIMIT = 500
AGGRESSIVE_RESULT_LIMIT = 100

HISTORY_MAX_CHARS = 5000
HISTORY_RECENT_RESULT_LIMIT = 300
HISTORY_OLD_RESULT_LIMIT = 80


def build_history_context(db: Database, plan_id: str, max_chars: int = HISTORY_MAX_CHARS) -> str:
    """Build a formatted history context string from plan snapshots and lineage."""
    snapshots = db.get_history_for_plan(plan_id)
    plan = db.get_plan(plan_id)

    if not snapshots and (not plan or not plan.parent_plan_id):
        return ""

    lines: list[str] = ["PLAN HISTORY:"]

    # Lineage info
    if plan and plan.parent_plan_id:
        parent = db.get_plan(plan.parent_plan_id)
        if parent:
            parent_snapshots = db.get_history_for_plan(parent.id)
            lines.append(
                f"This plan continues from: {parent.name}. "
                f"Parent had {len(parent_snapshots)} snapshot(s)."
            )

    if snapshots:
        for idx, snap in enumerate(snapshots):
            is_most_recent = (idx == len(snapshots) - 1)
            result_limit = HISTORY_RECENT_RESULT_LIMIT if is_most_recent else HISTORY_OLD_RESULT_LIMIT

            date_str = snap.snapshot_at[:10] if len(snap.snapshot_at) >= 10 else snap.snapshot_at
            lines.append("===")
            lines.append(f"Snapshot: \"{snap.snapshot_name}\" ({date_str})")
            if snap.summary:
                lines.append(f"Summary: {snap.summary}")

            # Parse steps_json for key results
            try:
                steps_data = json.loads(snap.steps_json)
            except (json.JSONDecodeError, TypeError):
                steps_data = []

            if steps_data:
                lines.append("Key results:")
                for s in steps_data:
                    result = s.get("result") or "(no output)"
                    if len(result) > result_limit:
                        result = result[:result_limit] + "... [truncated]"
                    lines.append(f"- Step {s.get('queue_position', 0) + 1} ({s.get('name', '?')}): {result}")
            lines.append("===")

    context = "\n".join(lines) + "\n"

    # Truncate if over budget
    if len(context) > max_chars:
        context = context[:max_chars - 20] + "\n... [truncated]\n"

    return context


def build_context(db: Database, plan_id: str, current_queue_position: int) -> str:
    """Build a formatted context string from all succeeded steps before the current position."""
    steps = db.get_steps_for_plan(plan_id)
    prior = [s for s in steps
             if s.queue_position < current_queue_position and s.status == StepStatus.SUCCEEDED]

    if not prior:
        return ""

    # First pass: build with normal truncation
    sections = []
    for s in prior:
        result = s.result or "(no output)"
        if len(result) > NORMAL_RESULT_LIMIT:
            result = result[:NORMAL_RESULT_LIMIT] + "... [truncated]"
        sections.append(
            f"Step {s.queue_position + 1} ({s.name}): {s.title}\n"
            f"Result: {result}"
        )

    context = _format_sections(sections)

    # If too long, truncate older steps more aggressively
    if len(context) > MAX_TOTAL_CHARS:
        sections = []
        for s in prior:
            result = s.result or "(no output)"
            if len(result) > AGGRESSIVE_RESULT_LIMIT:
                result = result[:AGGRESSIVE_RESULT_LIMIT] + "... [truncated]"
            sections.append(
                f"Step {s.queue_position + 1} ({s.name}): {s.title}\n"
                f"Result: {result}"
            )
        context = _format_sections(sections)

    return context


def _format_sections(sections: list[str]) -> str:
    lines = ["CONTEXT FROM PREVIOUS STEPS:", "---"]
    for section in sections:
        lines.append(section)
        lines.append("---")
    return "\n".join(lines) + "\n"
