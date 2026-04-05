from ..database import Database
from ..models import StepStatus

MAX_TOTAL_CHARS = 10000
NORMAL_RESULT_LIMIT = 500
AGGRESSIVE_RESULT_LIMIT = 100


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
