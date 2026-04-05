import subprocess
from datetime import datetime
from threading import Event
from typing import Callable, Optional

from ..config import Config
from ..database import Database
from ..models import AgentRun, PlanStep, StepStatus
from . import claude_runner


class Orchestrator:
    def __init__(self, db: Database, config: Config):
        self.db = db
        self.config = config

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

        # Run Claude
        exit_code, stdout, stderr = claude_runner.run_claude(
            step.prompt, working_dir, self.config
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

            # Build check
            if self.config.build_command:
                self._run_build_check(step, working_dir, on_output, cancel_event)
        else:
            error_msg = stderr or f"Exit code {exit_code}"
            step.status = StepStatus.FAILED
            step.result = output_text
            self.db.update_step(step)
            self._create_run_record(step, started_at, finished_at, "failed",
                                    output_text, error_msg, exit_code)
            on_output(f"\n[Step FAILED: {error_msg[:200]}]\n")
            on_step_failed(step, error_msg)

    def _run_build_check(
        self,
        step: PlanStep,
        working_dir: str,
        on_output: Callable[[str], None],
        cancel_event: Event,
    ) -> None:
        on_output(f"\n--- Running build check: {self.config.build_command} ---\n")
        try:
            result = subprocess.run(
                self.config.build_command,
                shell=True,
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                on_output("[Build OK]\n")
            else:
                on_output(f"[Build FAILED]\n{result.stdout}\n{result.stderr}\n")
                if self.config.auto_fix_build and not cancel_event.is_set():
                    self._attempt_auto_fix(step, working_dir, result, on_output)
        except subprocess.TimeoutExpired:
            on_output("[Build timed out after 120s]\n")
        except FileNotFoundError:
            on_output(f"[Build command not found: {self.config.build_command}]\n")

    def _attempt_auto_fix(
        self,
        step: PlanStep,
        working_dir: str,
        build_result: subprocess.CompletedProcess,
        on_output: Callable[[str], None],
    ) -> None:
        on_output("\n--- Attempting auto-fix ---\n")
        fix_prompt = (
            f"The build command `{self.config.build_command}` failed after the previous step. "
            f"Build output:\n{build_result.stdout}\n{build_result.stderr}\n\n"
            f"Please fix the build errors."
        )
        exit_code, stdout, stderr = claude_runner.run_claude(
            fix_prompt, working_dir, self.config
        )
        if stdout:
            on_output(stdout)
        if stderr:
            on_output(f"\n{stderr}")

        # Re-check build
        on_output(f"\n--- Re-checking build ---\n")
        try:
            recheck = subprocess.run(
                self.config.build_command,
                shell=True,
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if recheck.returncode == 0:
                on_output("[Build OK after auto-fix]\n")
            else:
                on_output(f"[Build still failing after auto-fix]\n{recheck.stdout}\n{recheck.stderr}\n")
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            on_output(f"[Build re-check error: {e}]\n")

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
