import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

from ..config import Config
from ..database import Database
from ..models import AutoModeSession, Plan, PlanStep, StepStatus
from . import claude_md_updater, claude_runner, step_generator
from .claude_md_updater import ClaudeMdUpdateError
from .context_builder import build_context
from .orchestrator import VERIFY_SUFFIX


@dataclass
class AutoModeCallbacks:
    on_status_change: Callable[[str], None]
    on_batch_started: Callable[[int, List[dict]], None]
    on_step_started: Callable[[int, str], None]
    on_step_completed: Callable[[int, str, str], None]
    on_step_failed: Callable[[int, str, str], None]
    on_retry_countdown: Callable[[int], None]
    on_batch_completed: Callable[[int, int, int], None]
    on_log: Callable[[str], None]
    on_session_ended: Callable[[str], None]


class AutoModeOrchestrator:
    def __init__(
        self,
        session: AutoModeSession,
        db: Database,
        config: Config,
        callbacks: AutoModeCallbacks,
    ):
        self.session = session
        self.db = db
        self.config = config
        self.callbacks = callbacks
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._completed_batch_summaries: List[dict] = []

    def start(self) -> None:
        self.session.status = "running"
        self.db.update_auto_mode_session(self.session)
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _run_loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                batch_num = self.session.current_batch

                # 1. Generate next batch (retry on StepGenerationError)
                self.callbacks.on_status_change("generating")
                self.callbacks.on_log(f"Generating batch {batch_num}...")

                steps = self._generate_with_retry(batch_num)
                if steps is None:
                    break

                # 2. Create plan in DB
                directive_short = self.session.directive[:60]
                plan = Plan(
                    name=f"Auto-mode batch {batch_num} - {directive_short}",
                    project_root=self.session.project_root,
                    auto_mode_session_id=self.session.id,
                )
                self.db.create_plan(plan)

                db_steps: List[PlanStep] = []
                for idx, step_dict in enumerate(steps):
                    ps = PlanStep(
                        plan_id=plan.id,
                        queue_position=idx,
                        name=step_dict.get("name", f"step-{idx + 1}"),
                        title=step_dict.get("title", f"Step {idx + 1}"),
                        prompt=step_dict.get("prompt", ""),
                        description=step_dict.get("description", ""),
                        status=StepStatus.PENDING,
                    )
                    self.db.create_step(ps)
                    db_steps.append(ps)

                self.callbacks.on_batch_started(batch_num, steps)
                self.callbacks.on_status_change("running")

                # 3. Execute each step
                succeeded = 0
                for idx, ps in enumerate(db_steps):
                    if self._stop_event.is_set():
                        break
                    ok = self._execute_step_with_retry(ps, plan, idx)
                    if not ok:
                        break
                    succeeded += 1

                if self._stop_event.is_set():
                    break

                # 4. Update CLAUDE.md (swallow errors)
                self.callbacks.on_status_change("updating_claude_md")
                completed_steps_info = [
                    {"name": s.name, "title": s.title, "result": s.result or ""}
                    for s in self.db.get_steps_for_plan(plan.id)
                ]
                try:
                    claude_md_updater.update_claude_md(
                        directive=self.session.directive,
                        project_root=self.session.project_root,
                        batch_number=batch_num,
                        completed_steps=completed_steps_info,
                        config=self.config,
                        on_log=self.callbacks.on_log,
                    )
                except ClaudeMdUpdateError:
                    pass

                # 5. Auto-snapshot
                self.db.create_history_snapshot(
                    plan.id,
                    f"Auto-mode batch {batch_num}",
                    summary=f"{succeeded} succeeded out of {len(db_steps)} steps",
                )

                # 6. Build summaries for next generation
                batch_step_summaries = []
                for s in self.db.get_steps_for_plan(plan.id):
                    result_excerpt = (s.result or "")[:100].replace("\n", " ")
                    batch_step_summaries.append({
                        "name": s.name,
                        "title": s.title,
                        "status": s.status.value,
                        "result_excerpt": result_excerpt,
                    })
                self._completed_batch_summaries.append({
                    "batch": batch_num,
                    "steps": batch_step_summaries,
                })

                # 7. Increment batch, persist
                self.session.current_batch += 1
                self.db.update_auto_mode_session(self.session)

                self.callbacks.on_batch_completed(batch_num, succeeded, 0)

        finally:
            self.session.status = "stopped"
            self.db.update_auto_mode_session(self.session)
            self.callbacks.on_status_change("stopped")
            self.callbacks.on_session_ended("stopped")

    def _generate_with_retry(self, batch_num: int) -> Optional[List[dict]]:
        while not self._stop_event.is_set():
            try:
                return step_generator.generate_next_steps(
                    directive=self.session.directive,
                    project_root=self.session.project_root,
                    batch_number=batch_num,
                    completed_batch_summaries=self._completed_batch_summaries,
                    config=self.config,
                )
            except step_generator.StepGenerationError as e:
                self.callbacks.on_log(
                    f"Step generation failed (exit {e.exit_code}): {e.stderr[:200]}"
                )
                self.callbacks.on_status_change("waiting_retry")
                self._wait_with_countdown(self.config.auto_mode_retry_wait_seconds)
                if self._stop_event.is_set():
                    return None
                self.callbacks.on_status_change("generating")
        return None

    def _execute_step_with_retry(self, step: PlanStep, plan: Plan, step_index: int) -> bool:
        while True:
            if self._stop_event.is_set():
                return False

            self.callbacks.on_step_started(step_index, step.title)
            step.status = StepStatus.RUNNING
            self.db.update_step(step)

            context = build_context(self.db, plan.id, step.queue_position)
            directive_preamble = f"DIRECTIVE:\n{self.session.directive}\n\n"
            if context:
                full_prompt = directive_preamble + context + "TASK:\n" + step.prompt + VERIFY_SUFFIX
            else:
                full_prompt = directive_preamble + "TASK:\n" + step.prompt + VERIFY_SUFFIX

            exit_code, stdout, stderr = claude_runner.run_claude(
                full_prompt, self.session.project_root, self.config
            )

            if exit_code == 0:
                step.status = StepStatus.SUCCEEDED
                step.result = stdout
                self.db.update_step(step)
                result_excerpt = (stdout or "")[:200].replace("\n", " ")
                self.callbacks.on_step_completed(step_index, step.title, result_excerpt)
                self.session.total_steps_executed += 1
                self.db.update_auto_mode_session(self.session)
                return True

            error_msg = stderr or f"Exit code {exit_code}"
            step.status = StepStatus.FAILED
            step.result = (stdout or "") + (f"\n--- STDERR ---\n{stderr}" if stderr else "")
            self.db.update_step(step)
            self.callbacks.on_step_failed(step_index, step.title, error_msg)
            self.session.total_steps_executed += 1
            self.db.update_auto_mode_session(self.session)

            self.callbacks.on_status_change("waiting_retry")
            self._wait_with_countdown(self.config.auto_mode_retry_wait_seconds)

            if self._stop_event.is_set():
                return False

            self.callbacks.on_status_change("running")
            # loop continues — retry same step

    def _wait_with_countdown(self, seconds: int) -> None:
        for remaining in range(seconds, 0, -1):
            if self._stop_event.is_set():
                return
            self.callbacks.on_retry_countdown(remaining)
            time.sleep(1)
