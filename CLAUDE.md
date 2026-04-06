# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ClaudeCode Orchestrator — a Python tkinter GUI that orchestrates multi-step Claude Code agent executions with plan management, step queuing, context sharing between steps, and execution history via SQLite.

## Commands

```bash
# Run the GUI
python -m src.orchestrator.main

# Run all tests
python -m unittest discover -s tests -v

# Run a single test file
python -m unittest tests.test_database -v
```

## Dependencies

- Python 3.10+ (uses `X | None` type union syntax)
- No external packages — stdlib only (tkinter, sqlite3, subprocess, json, threading)
- Optional: `tkinterdnd2` for drag-and-drop (gracefully skipped if missing)
- Requires `claude` CLI on PATH for step execution

## Architecture

**Models** (`src/orchestrator/models.py`): Three dataclasses — `Plan`, `PlanStep`, `AgentRun` — with uuid-based IDs and a `StepStatus` enum.

**Database** (`src/orchestrator/database.py`): Thin SQLite wrapper with CRUD for plans, steps, and agent runs. Uses `check_same_thread=False` for cross-thread access from the GUI.

**Services** (`src/orchestrator/services/`):
- `orchestrator.py` — Execution engine. Runs steps sequentially in background threads. Appends a `VERIFY_SUFFIX` to prompts for automatic build verification. Supports cancellation via `threading.Event`.
- `claude_runner.py` — Spawns `claude` CLI as a subprocess with `-p -` for stdin piping. Passes budget, turns, tools, and permission-mode flags from config.
- `context_builder.py` — Injects prior succeeded step results into the current step's prompt. Two-pass truncation: 500 chars per step normally, 100 chars if total exceeds 10K.
- `json_parser.py` — Extracts JSON from Claude output using 4 fallback strategies (direct parse → strip markdown → bracket scan → extract "steps" key).

**UI** (`src/orchestrator/ui/`): Dialog modules for plan creation, step editing, settings, import preview, and log viewing. The main app class (`main.py`) manages all UI state, threading, and per-plan execution tracking with `queue.Queue` for thread-safe UI updates.

## Key Design Patterns

- **Per-plan execution state**: Each plan tracks its own `cancel_event`, output queue, and status independently, enabling concurrent plan execution.
- **Callback-driven execution**: The orchestrator service communicates progress back to the UI via callback functions, keeping services UI-agnostic.
- **Config as dataclass**: `config.py` merges `config.json` overrides with defaults; unknown keys are silently ignored.
