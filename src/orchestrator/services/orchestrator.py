from datetime import datetime
from threading import Event
from typing import Callable, Optional

from ..config import Config
from ..database import Database
from ..models import AgentRun, PlanStep, StepStatus
from . import claude_runner
from .context_builder import build_context, build_history_context


# Appended to every step prompt so Claude auto-verifies the project
VERIFY_SUFFIX = (
    "\n\nIMPORTANT: After completing this step, verify that the project still "
    "builds/runs correctly. Detect the project type from the files present "
    "(e.g. package.json, *.csproj, *.sln, setup.py, pyproject.toml, Makefile, Cargo.toml, etc.) "
    "and run the appropriate build/test/lint command. If something breaks, fix it before finishing. "
    "Commit your changes with a descriptive commit message."
)


class Orchestrator:
    def __init__(self, db: Database, config: Config, include_context: bool = True):
        self.db = db
        self.config = config
        self.include_context = include_context

    def execute_queue(
        self,
        plan_id: str,
        on_step_started: Callable[[PlanStep, int, int], None],
        on_step_completed: Callable[[PlanStep], None],
        on_step_failed: Callable[[PlanStep, str], None],
        on_output: Callable[[str], None],
        cancel_event: Event,
    ) -> None:
        """Execute all pending/queued steps for a plan in order."""
        steps = self.db.get_steps_for_plan(plan_id)
        runnable = [s for s in steps if s.status in (StepStatus.PENDING, StepStatus.QUEUED)]
        total = len(runnable)

        plan = self.db.get_plan(plan_id)
        working_dir = plan.project_root if plan else "."

        for idx, step in enumerate(runnable):
            if cancel_event.is_set():
                on_output("\n--- Execution cancelled by user ---\n")
                break

            self._execute_step(step, working_dir, idx + 1, total,
                               on_step_started, on_step_completed, on_step_failed,
                               on_output, cancel_event)

        # Auto-snapshot after queue run completes
        if not cancel_event.is_set() and runnable:
            self._auto_snapshot(plan_id, runnable)

    def execute_single_step(
        self,
        step_id: str,
        on_step_started: Callable[[PlanStep, int, int], None],
        on_step_completed: Callable[[PlanStep], None],
        on_step_failed: Callable[[PlanStep, str], None],
        on_output: Callable[[str], None],
        cancel_event: Event,
    ) -> None:
        """Execute a single step by ID."""
        step = self.db.get_step(step_id)
        if not step:
            on_output(f"Step {step_id} not found.\n")
            return
        plan = self.db.get_plan(step.plan_id)
        working_dir = plan.project_root if plan else "."
        self._execute_step(step, working_dir, 1, 1,
                           on_step_started, on_step_completed, on_step_failed,
                           on_output, cancel_event)

    def _execute_step(
        self,
        step: PlanStep,
        working_dir: str,
        step_num: int,
        total: int,
        on_step_started: Callable,
        on_step_completed: Callable,
        on_step_failed: Callable,
        on_output: Callable,
        cancel_event: Event,
    ) -> None:
        # Mark running
        step.status = StepStatus.RUNNING
        self.db.update_step(step)
        on_step_started(step, step_num, total)
        on_output(f"\n{'='*60}\n")
        on_output(f"Step {step_num}/{total}: {step.title}\n")
        on_output(f"{'='*60}\n\n")

        started_at = datetime.now().isoformat()

        # Build the full prompt with optional history + step context + auto-verify suffix
        full_prompt = step.prompt + VERIFY_SUFFIX
        if self.include_context and self.config.include_context:
            history_ctx = ""
            if self.config.include_history_context:
                history_ctx = build_history_context(self.db, step.plan_id)
            step_ctx = build_context(self.db, step.plan_id, step.queue_position)
            prefix = history_ctx + step_ctx
            if prefix:
                full_prompt = prefix + "TASK:\n" + step.prompt + VERIFY_SUFFIX

        # Run Claude
        exit_code, stdout, stderr = claude_runner.run_claude(
            full_prompt, working_dir, self.config
        )

        finished_at = datetime.now().isoformat()
        output_text = stdout or ""
        if stderr:
            output_text += f"\n--- STDERR ---\n{stderr}"

        on_output(output_text)

        if exit_code == 0:
            step.status = StepStatus.SUCCEEDED
            step.result = stdout
            self.db.update_step(step)
            self._create_run_record(step, started_at, finished_at, "succeeded",
                                    output_text, None, exit_code)
            on_output(f"\n[Step SUCCEEDED]\n")
            on_step_completed(step)
        else:
            error_msg = stderr or f"Exit code {exit_code}"
            step.status = StepStatus.FAILED
            step.result = output_text
            self.db.update_step(step)
            self._create_run_record(step, started_at, finished_at, "failed",
                                    output_text, error_msg, exit_code)
            on_output(f"\n[Step FAILED: {error_msg[:200]}]\n")
            on_step_failed(step, error_msg)

    def _create_run_record(
        self,
        step: PlanStep,
        started_at: str,
        finished_at: str,
        status: str,
        output: Optional[str],
        error_message: Optional[str],
        exit_code: Optional[int],
    ) -> None:
        existing_runs = self.db.get_runs_for_step(step.id)
        attempt = len(existing_runs) + 1
        run = AgentRun(
            step_id=step.id,
            attempt_number=attempt,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            output=output,
            error_message=error_message,
            exit_code=exit_code,
        )
        self.db.create_agent_run(run)

    def _auto_snapshot(self, plan_id: str, executed_steps: list[PlanStep]) -> None:
        # Re-read steps to get final statuses
        steps = self.db.get_steps_for_plan(plan_id)
        executed_ids = {s.id for s in executed_steps}
        relevant = [s for s in steps if s.id in executed_ids]
        succeeded = sum(1 for s in relevant if s.status == StepStatus.SUCCEEDED)
        failed = sum(1 for s in relevant if s.status == StepStatus.FAILED)
        summary = f"{succeeded} succeeded, {failed} failed out of {len(relevant)} steps"
        self.db.create_history_snapshot(
            plan_id,
            "Auto-snapshot after queue run",
            summary=summary,
        )
