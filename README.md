# ClaudeCode Orchestrator

A Python application that orchestrates multi-step Claude Code agent executions with plan management, step queuing, and live output.

The orchestrator (`src/orchestrator/`) provides a tkinter GUI for creating plans, managing step queues, and executing Claude Code agents with context sharing between steps.

![alt text](show.PNG "Program")

### Requirements

- Python 3.10+
- No external dependencies (stdlib only; `tkinterdnd2` optional for drag-and-drop)

### Running

```bash
# Launch the GUI
run.cmd
# or directly:
python -m src.orchestrator.main
```

### Running Tests

```bash
run-tests.cmd
# or directly:
python -m unittest discover -s tests -v
```

### Project Structure

```
src/orchestrator/
  main.py              # Main tkinter application
  models.py            # Plan, PlanStep, AgentRun dataclasses
  database.py          # SQLite CRUD layer
  config.py            # Configuration management
  services/
    orchestrator.py    # Step execution engine
    claude_runner.py   # Claude CLI subprocess wrapper
    context_builder.py # Context injection from prior steps
  ui/
    new_plan_dialog.py       # Plan creation with Claude splitting
    step_editor_dialog.py    # Step editing dialog
    settings_dialog.py       # Settings dialog
    import_preview_dialog.py # Import preview with drag-and-drop
    log_viewer.py            # Execution log viewer
```
