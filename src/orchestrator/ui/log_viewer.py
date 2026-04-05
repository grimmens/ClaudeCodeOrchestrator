import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from typing import Optional

from ..database import Database
from ..models import AgentRun, PlanStep


class LogViewer(tk.Toplevel):
    """Toplevel window showing AgentRun records for a plan or a specific step."""

    def __init__(self, parent, db: Database, plan_id: str,
                 filter_step_id: Optional[str] = None):
        super().__init__(parent)
        self.db = db
        self.plan_id = plan_id
        self.filter_step_id = filter_step_id

        plan = db.get_plan(plan_id)
        plan_name = plan.name if plan else "Unknown"

        if filter_step_id:
            step = db.get_step(filter_step_id)
            step_name = step.name if step else "Unknown"
            self.title(f"Run History - Step: {step_name}")
        else:
            self.title(f"Run History - Plan: {plan_name}")

        self.geometry("1000x650")
        self.minsize(800, 500)

        # Build a mapping of step_id -> step for lookups
        self._steps: dict[str, PlanStep] = {}
        for s in db.get_steps_for_plan(plan_id):
            self._steps[s.id] = s

        self._runs: list[AgentRun] = []

        self._build_ui()
        self._load_runs()

    def _build_ui(self):
        # Top: toolbar
        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, padx=5, pady=5)

        ttk.Button(toolbar, text="Refresh", command=self._load_runs).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Clear History", command=self._clear_history).pack(side=tk.LEFT, padx=2)

        # Main paned window: treeview on top, output/error on bottom
        pane = ttk.PanedWindow(self, orient=tk.VERTICAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        # Treeview
        tree_frame = ttk.Frame(pane)
        pane.add(tree_frame, weight=1)

        columns = ("Step Name", "Attempt", "Status", "Started", "Duration", "Exit Code", "Cost USD")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")
        for col in columns:
            self.tree.heading(col, text=col)

        self.tree.column("Step Name", width=150)
        self.tree.column("Attempt", width=60, stretch=False)
        self.tree.column("Status", width=80, stretch=False)
        self.tree.column("Started", width=150)
        self.tree.column("Duration", width=80, stretch=False)
        self.tree.column("Exit Code", width=70, stretch=False)
        self.tree.column("Cost USD", width=80, stretch=False)

        tree_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(fill=tk.BOTH, expand=True)

        self.tree.bind("<<TreeviewSelect>>", self._on_run_selected)

        # Bottom: output and error in a horizontal pane
        detail_pane = ttk.PanedWindow(pane, orient=tk.HORIZONTAL)
        pane.add(detail_pane, weight=1)

        # Output panel
        out_frame = ttk.LabelFrame(detail_pane, text="Output")
        detail_pane.add(out_frame, weight=1)

        self.output_text = tk.Text(out_frame, wrap=tk.WORD, state=tk.DISABLED)
        out_scroll = ttk.Scrollbar(out_frame, orient=tk.VERTICAL, command=self.output_text.yview)
        self.output_text.configure(yscrollcommand=out_scroll.set)
        out_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.output_text.pack(fill=tk.BOTH, expand=True)

        # Error panel
        err_frame = ttk.LabelFrame(detail_pane, text="Error")
        detail_pane.add(err_frame, weight=1)

        self.error_text = tk.Text(err_frame, wrap=tk.WORD, state=tk.DISABLED)
        err_scroll = ttk.Scrollbar(err_frame, orient=tk.VERTICAL, command=self.error_text.yview)
        self.error_text.configure(yscrollcommand=err_scroll.set)
        err_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.error_text.pack(fill=tk.BOTH, expand=True)

    def _load_runs(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        if self.filter_step_id:
            self._runs = self.db.get_runs_for_step(self.filter_step_id)
        else:
            self._runs = self.db.get_runs_for_plan(self.plan_id)

        for run in self._runs:
            step = self._steps.get(run.step_id)
            step_name = step.name if step else "(deleted)"
            duration = self._calc_duration(run.started_at, run.finished_at)
            cost = f"${run.cost_usd:.4f}" if run.cost_usd is not None else ""
            exit_code = str(run.exit_code) if run.exit_code is not None else ""
            started = run.started_at or ""

            self.tree.insert("", tk.END, iid=run.id, values=(
                step_name, run.attempt_number, run.status,
                started, duration, exit_code, cost,
            ))

    def _on_run_selected(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        run = next((r for r in self._runs if r.id == sel[0]), None)
        if not run:
            return

        self.output_text.config(state=tk.NORMAL)
        self.output_text.delete("1.0", tk.END)
        self.output_text.insert("1.0", run.output or "(no output)")
        self.output_text.config(state=tk.DISABLED)

        self.error_text.config(state=tk.NORMAL)
        self.error_text.delete("1.0", tk.END)
        self.error_text.insert("1.0", run.error_message or "(no error)")
        self.error_text.config(state=tk.DISABLED)

    def _clear_history(self):
        if self.filter_step_id:
            msg = "Delete all run history for this step?"
        else:
            msg = "Delete all run history for this plan?"

        if not messagebox.askyesno("Clear History", msg, parent=self):
            return

        if self.filter_step_id:
            self.db.delete_runs_for_step(self.filter_step_id)
        else:
            self.db.delete_runs_for_plan(self.plan_id)

        self._load_runs()
        # Clear detail panels
        self.output_text.config(state=tk.NORMAL)
        self.output_text.delete("1.0", tk.END)
        self.output_text.config(state=tk.DISABLED)
        self.error_text.config(state=tk.NORMAL)
        self.error_text.delete("1.0", tk.END)
        self.error_text.config(state=tk.DISABLED)

    @staticmethod
    def _calc_duration(started: str | None, finished: str | None) -> str:
        if not started or not finished:
            return ""
        try:
            fmt = "%Y-%m-%dT%H:%M:%S"
            # Handle fractional seconds by truncating
            s = started.split(".")[0]
            f = finished.split(".")[0]
            delta = datetime.fromisoformat(f) - datetime.fromisoformat(s)
            total_seconds = int(delta.total_seconds())
            if total_seconds < 0:
                return ""
            minutes, seconds = divmod(total_seconds, 60)
            if minutes > 0:
                return f"{minutes}m {seconds}s"
            return f"{seconds}s"
        except (ValueError, TypeError):
            return ""
