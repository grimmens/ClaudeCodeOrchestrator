"""Robust JSON extraction from Claude CLI output.

Claude often wraps JSON in markdown fences, adds preamble/postscript text,
or returns slightly unexpected formats.  This module provides multi-strategy
parsing so the orchestrator can recover gracefully.
"""

import json
import re


def extract_json_steps(text: str) -> tuple[list[dict], list[str]]:
    """Extract a JSON array of step objects from Claude's raw text output.

    Tries multiple strategies in order of reliability:
      1. Direct JSON parse of the full text
      2. Strip markdown code fences and parse the inner content
      3. Find the outermost JSON array via bracket scanning
      4. Find a JSON object with a "steps" key and extract the array

    Returns:
        (steps, warnings) – a list of step dicts and any non-fatal warnings.

    Raises:
        ValueError: when no valid JSON array of steps can be recovered.
    """
    text = text.strip()
    if not text:
        raise ValueError("Claude returned empty output")

    warnings: list[str] = []

    # --- Strategy 1: direct parse ----------------------------------------
    result = _try_direct_parse(text)
    if result is not None:
        return _validate_steps(result, warnings)

    # --- Strategy 2: strip markdown fences --------------------------------
    stripped = _strip_markdown_fences(text)
    if stripped != text:
        result = _try_direct_parse(stripped)
        if result is not None:
            warnings.append("Stripped markdown code fences from response")
            return _validate_steps(result, warnings)

    # --- Strategy 3: find outermost [ ... ] -------------------------------
    result = _find_json_array(text)
    if result is not None:
        warnings.append("Extracted JSON array from surrounding text")
        return _validate_steps(result, warnings)

    # --- Strategy 4: find { "steps": [...] } object -----------------------
    result = _find_steps_object(text)
    if result is not None:
        warnings.append("Extracted steps from JSON object wrapper")
        return _validate_steps(result, warnings)

    # --- All strategies failed --------------------------------------------
    preview = text[:300] + ("..." if len(text) > 300 else "")
    raise ValueError(
        f"Could not extract a JSON array of steps from Claude's response.\n\n"
        f"Raw output (first 300 chars):\n{preview}"
    )


# ── Internal helpers ────────────────────────────────────────────────────

def _try_direct_parse(text: str):
    """Try json.loads; return parsed value or None."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


_FENCE_RE = re.compile(
    r"```(?:json|JSON)?\s*\n(.*?)```",
    re.DOTALL,
)


def _strip_markdown_fences(text: str) -> str:
    """Return the content inside the first markdown code fence, or the original text."""
    m = _FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    return text


def _find_json_array(text: str) -> list | None:
    """Scan for the outermost balanced [ ... ] and parse it."""
    start = text.find("[")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                parsed = _try_direct_parse(candidate)
                if isinstance(parsed, list):
                    return parsed
                return None
    return None


def _find_steps_object(text: str) -> list | None:
    """Scan for the outermost { ... } that contains a "steps" key."""
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                parsed = _try_direct_parse(candidate)
                if isinstance(parsed, dict) and "steps" in parsed:
                    return parsed["steps"]
                return None
    return None


def _validate_steps(data, warnings: list[str]) -> tuple[list[dict], list[str]]:
    """Ensure *data* is a list of dicts with at least a name or title, and
    normalise each entry so downstream code can rely on consistent keys."""
    if isinstance(data, dict) and "steps" in data:
        data = data["steps"]
        warnings.append("Unwrapped top-level 'steps' key")

    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON array of steps, got {type(data).__name__}")

    if len(data) == 0:
        raise ValueError("Claude returned an empty steps array")

    steps: list[dict] = []
    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            warnings.append(f"Skipped non-object entry at index {i}")
            continue

        # Normalise common alternative key names
        step = _normalise_step(entry, i)
        steps.append(step)

    if not steps:
        raise ValueError("No valid step objects found in the array")

    return steps, warnings


def _normalise_step(raw: dict, index: int) -> dict:
    """Map common key variants to the canonical name/title/prompt schema."""
    name = (
        raw.get("name")
        or raw.get("step")
        or raw.get("id")
        or raw.get("step_name")
        or f"step-{index + 1}"
    )
    title = (
        raw.get("title")
        or raw.get("summary")
        or raw.get("heading")
        or raw.get("description", "")
    )
    prompt = (
        raw.get("prompt")
        or raw.get("instructions")
        or raw.get("details")
        or raw.get("task")
        or raw.get("command")
        or ""
    )
    description = raw.get("description") or ""

    return {
        "name": str(name),
        "title": str(title),
        "prompt": str(prompt),
        "description": str(description),
    }
