import json
import sqlite3
from datetime import datetime
from typing import List, Optional

from .models import AgentRun, Plan, PlanHistory, PlanStep, StepStatus


class Database:
    def __init__(self, db_path: str = "orchestrator.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS plans (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                project_root TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS plan_steps (
                id TEXT PRIMARY KEY,
                plan_id TEXT NOT NULL,
                queue_position INTEGER NOT NULL,
                name TEXT NOT NULL,
                title TEXT NOT NULL,
                prompt TEXT NOT NULL,
                description TEXT,
                result TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                FOREIGN KEY (plan_id) REFERENCES plans(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS agent_runs (
                id TEXT PRIMARY KEY,
                step_id TEXT NOT NULL,
                attempt_number INTEGER NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                output TEXT,
                error_message TEXT,
                exit_code INTEGER,
                cost_usd REAL,
                FOREIGN KEY (step_id) REFERENCES plan_steps(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS plan_history (
                id TEXT PRIMARY KEY,
                plan_id TEXT NOT NULL,
                snapshot_name TEXT NOT NULL,
                snapshot_at TEXT NOT NULL,
                summary TEXT,
                steps_json TEXT NOT NULL,
                FOREIGN KEY (plan_id) REFERENCES plans(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS plan_templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                steps_json TEXT NOT NULL,
                created_from_plan_id TEXT,
                created_at TEXT NOT NULL
            );
        """)
        self.conn.commit()

        # Add parent_plan_id column if it doesn't exist (idempotent migration)
        try:
            self.conn.execute("ALTER TABLE plans ADD COLUMN parent_plan_id TEXT")
            self.conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists

    # -- Plans --

    def create_plan(self, plan: Plan) -> Plan:
        self.conn.execute(
            "INSERT INTO plans (id, name, project_root, created_at, parent_plan_id) VALUES (?, ?, ?, ?, ?)",
            (plan.id, plan.name, plan.project_root, plan.created_at, plan.parent_plan_id),
        )
        self.conn.commit()
        return plan

    def get_plans(self) -> List[Plan]:
        rows = self.conn.execute("SELECT * FROM plans ORDER BY created_at DESC").fetchall()
        return [Plan(**dict(r)) for r in rows]

    def get_plan(self, plan_id: str) -> Optional[Plan]:
        row = self.conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
        return Plan(**dict(row)) if row else None

    def update_plan(self, plan: Plan) -> None:
        self.conn.execute(
            "UPDATE plans SET name=?, project_root=? WHERE id=?",
            (plan.name, plan.project_root, plan.id),
        )
        self.conn.commit()

    def delete_plan(self, plan_id: str) -> None:
        self.conn.execute("DELETE FROM plan_history WHERE plan_id = ?", (plan_id,))
        self.conn.execute("DELETE FROM plan_steps WHERE plan_id = ?", (plan_id,))
        self.conn.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
        self.conn.commit()

    # -- Steps --

    def create_step(self, step: PlanStep) -> PlanStep:
        self.conn.execute(
            "INSERT INTO plan_steps (id, plan_id, queue_position, name, title, prompt, description, result, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (step.id, step.plan_id, step.queue_position, step.name, step.title,
             step.prompt, step.description, step.result, step.status.value),
        )
        self.conn.commit()
        return step

    def get_step(self, step_id: str) -> Optional[PlanStep]:
        row = self.conn.execute("SELECT * FROM plan_steps WHERE id = ?", (step_id,)).fetchone()
        return self._row_to_step(row) if row else None

    def get_steps_for_plan(self, plan_id: str) -> List[PlanStep]:
        rows = self.conn.execute(
            "SELECT * FROM plan_steps WHERE plan_id = ? ORDER BY queue_position", (plan_id,)
        ).fetchall()
        return [self._row_to_step(r) for r in rows]

    def update_step(self, step: PlanStep) -> None:
        self.conn.execute(
            "UPDATE plan_steps SET queue_position=?, name=?, title=?, prompt=?, description=?, result=?, status=? "
            "WHERE id=?",
            (step.queue_position, step.name, step.title, step.prompt,
             step.description, step.result, step.status.value, step.id),
        )
        self.conn.commit()

    def delete_step(self, step_id: str) -> None:
        self.conn.execute("DELETE FROM plan_steps WHERE id = ?", (step_id,))
        self.conn.commit()

    def reorder_steps(self, plan_id: str, step_ids: List[str]) -> None:
        for position, step_id in enumerate(step_ids):
            self.conn.execute(
                "UPDATE plan_steps SET queue_position = ? WHERE id = ? AND plan_id = ?",
                (position, step_id, plan_id),
            )
        self.conn.commit()

    # -- Agent Runs --

    def create_agent_run(self, run: AgentRun) -> AgentRun:
        self.conn.execute(
            "INSERT INTO agent_runs (id, step_id, attempt_number, status, started_at, finished_at, output, error_message, exit_code, cost_usd) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run.id, run.step_id, run.attempt_number, run.status, run.started_at,
             run.finished_at, run.output, run.error_message, run.exit_code, run.cost_usd),
        )
        self.conn.commit()
        return run

    def get_runs_for_step(self, step_id: str) -> List[AgentRun]:
        rows = self.conn.execute(
            "SELECT * FROM agent_runs WHERE step_id = ? ORDER BY attempt_number", (step_id,)
        ).fetchall()
        return [AgentRun(**dict(r)) for r in rows]

    def get_runs_for_plan(self, plan_id: str) -> List[AgentRun]:
        rows = self.conn.execute(
            "SELECT ar.* FROM agent_runs ar "
            "JOIN plan_steps ps ON ar.step_id = ps.id "
            "WHERE ps.plan_id = ? ORDER BY ar.started_at",
            (plan_id,),
        ).fetchall()
        return [AgentRun(**dict(r)) for r in rows]

    def delete_runs_for_plan(self, plan_id: str) -> None:
        self.conn.execute(
            "DELETE FROM agent_runs WHERE step_id IN "
            "(SELECT id FROM plan_steps WHERE plan_id = ?)",
            (plan_id,),
        )
        self.conn.commit()

    def delete_runs_for_step(self, step_id: str) -> None:
        self.conn.execute("DELETE FROM agent_runs WHERE step_id = ?", (step_id,))
        self.conn.commit()

    # -- Plan History --

    def create_history_snapshot(self, plan_id: str, snapshot_name: str, summary: str | None = None) -> PlanHistory:
        steps = self.get_steps_for_plan(plan_id)
        steps_data = [
            {
                "id": s.id,
                "plan_id": s.plan_id,
                "queue_position": s.queue_position,
                "name": s.name,
                "title": s.title,
                "prompt": s.prompt,
                "description": s.description,
                "result": s.result,
                "status": s.status.value,
            }
            for s in steps
        ]
        snapshot = PlanHistory(
            plan_id=plan_id,
            snapshot_name=snapshot_name,
            summary=summary,
            steps_json=json.dumps(steps_data),
        )
        self.conn.execute(
            "INSERT INTO plan_history (id, plan_id, snapshot_name, snapshot_at, summary, steps_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (snapshot.id, snapshot.plan_id, snapshot.snapshot_name,
             snapshot.snapshot_at, snapshot.summary, snapshot.steps_json),
        )
        self.conn.commit()
        return snapshot

    def get_history_for_plan(self, plan_id: str) -> List[PlanHistory]:
        rows = self.conn.execute(
            "SELECT * FROM plan_history WHERE plan_id = ? ORDER BY snapshot_at",
            (plan_id,),
        ).fetchall()
        return [PlanHistory(**dict(r)) for r in rows]

    def get_full_lineage_history(self, plan_id: str) -> List[PlanHistory]:
        all_history: List[PlanHistory] = []
        current_id: str | None = plan_id
        visited: set[str] = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            all_history.extend(self.get_history_for_plan(current_id))
            plan = self.get_plan(current_id)
            current_id = plan.parent_plan_id if plan else None
        # Sort all collected history by snapshot_at
        all_history.sort(key=lambda h: h.snapshot_at)
        return all_history

    def delete_history_snapshot(self, snapshot_id: str) -> None:
        self.conn.execute("DELETE FROM plan_history WHERE id = ?", (snapshot_id,))
        self.conn.commit()

    # -- Plan Templates --

    def create_template(self, name: str, steps_json: str, description: str | None = None,
                        created_from_plan_id: str | None = None) -> dict:
        import uuid
        template_id = str(uuid.uuid4())
        created_at = datetime.now().isoformat()
        self.conn.execute(
            "INSERT INTO plan_templates (id, name, description, steps_json, created_from_plan_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (template_id, name, description, steps_json, created_from_plan_id, created_at),
        )
        self.conn.commit()
        return {"id": template_id, "name": name, "description": description,
                "steps_json": steps_json, "created_from_plan_id": created_from_plan_id,
                "created_at": created_at}

    def get_templates(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM plan_templates ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_template(self, template_id: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM plan_templates WHERE id = ?", (template_id,)
        ).fetchone()
        return dict(row) if row else None

    def delete_template(self, template_id: str) -> None:
        self.conn.execute("DELETE FROM plan_templates WHERE id = ?", (template_id,))
        self.conn.commit()

    @staticmethod
    def _row_to_step(row) -> PlanStep:
        d = dict(row)
        d["status"] = StepStatus(d["status"])
        return PlanStep(**d)
