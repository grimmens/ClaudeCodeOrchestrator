import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional

from ..database import Database
from ..models import PlanStep, StepStatus


class StepEditorDialog(tk.Toplevel):
    """Dialog for creating or editing a PlanStep."""

    def __init__(self, parent, db: Database, step: Optional[PlanStep] = None,
                 plan_id: str = "", insert_position: int = 0, on_saved=None):
        super().__init__(parent)
        self.db = db
        self.step = step
        self.plan_id = plan_id
        self.insert_position = insert_position
        self.on_saved = on_saved
        self.is_new = step is None

        self.title("Add Step" if self.is_new else f"Edit Step - {step.name}")
        self.geometry("700x700")
        self.transient(parent)
        self.grab_set()

        self._build_ui()

        if not self.is_new:
            self._populate(step)

    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # Name
        ttk.Label(self, text="Name (kebab-case):").pack(anchor=tk.W, **pad)
        self.name_var = tk.StringVar()
        ttk.Entry(self, textvariable=self.name_var).pack(fill=tk.X, **pad)

        # Title
        ttk.Label(self, text="Title:").pack(anchor=tk.W, **pad)
        self.title_var = tk.StringVar()
        ttk.Entry(self, textvariable=self.title_var).pack(fill=tk.X, **pad)

        # Prompt
        ttk.Label(self, text="Prompt (instruction for Claude):").pack(anchor=tk.W, **pad)
        self.prompt_text = tk.Text(self, height=8, wrap=tk.WORD)
        self.prompt_text.pack(fill=tk.X, **pad)

        # Description
        ttk.Label(self, text="Description (optional notes):").pack(anchor=tk.W, **pad)
        self.desc_text = tk.Text(self, height=4, wrap=tk.WORD)
        self.desc_text.pack(fill=tk.X, **pad)

        # Status
        status_frame = ttk.Frame(self)
        status_frame.pack(fill=tk.X, **pad)
        ttk.Label(status_frame, text="Status:").pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value=StepStatus.PENDING.value)
        self.status_combo = ttk.Combobox(
            status_frame, textvariable=self.status_var,
            values=[s.value for s in StepStatus], state="readonly", width=15,
        )
        self.status_combo.pack(side=tk.LEFT, padx=(4, 0))

        # Result
        ttk.Label(self, text="Result (Claude's output):").pack(anchor=tk.W, **pad)
        result_frame = ttk.Frame(self)
        result_frame.pack(fill=tk.BOTH, expand=True, **pad)
        self.result_text = tk.Text(result_frame, wrap=tk.WORD, state=tk.DISABLED)
        result_scroll = ttk.Scrollbar(result_frame, orient=tk.VERTICAL, command=self.result_text.yview)
        self.result_text.configure(yscrollcommand=result_scroll.set)
        result_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.result_text.pack(fill=tk.BOTH, expand=True)

        # Buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, **pad, pady=(8, 8))
        ttk.Button(btn_frame, text="Save", command=self._save).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.LEFT, padx=4)

    def _populate(self, step: PlanStep):
        self.name_var.set(step.name)
        self.title_var.set(step.title)

        self.prompt_text.insert("1.0", step.prompt or "")
        self.desc_text.insert("1.0", step.description or "")
        self.status_var.set(step.status.value)

        # Disable status combo if step is currently running
        if step.status == StepStatus.RUNNING:
            self.status_combo.config(state=tk.DISABLED)

        self.result_text.config(state=tk.NORMAL)
        self.result_text.insert("1.0", step.result or "")
        self.result_text.config(state=tk.DISABLED)

    def _save(self):
        name = self.name_var.get().strip()
        title = self.title_var.get().strip()
        prompt = self.prompt_text.get("1.0", tk.END).strip()

        if not name:
            messagebox.showwarning("Missing Name", "Please enter a step name.", parent=self)
            return
        if not title:
            messagebox.showwarning("Missing Title", "Please enter a step title.", parent=self)
            return

        description = self.desc_text.get("1.0", tk.END).strip() or None
        status = StepStatus(self.status_var.get())

        if self.is_new:
            new_step = PlanStep(
                plan_id=self.plan_id,
                queue_position=self.insert_position,
                name=name,
                title=title,
                prompt=prompt,
                description=description,
                status=status,
            )
            self.db.create_step(new_step)
        else:
            self.step.name = name
            self.step.title = title
            self.step.prompt = prompt
            self.step.description = description
            self.step.status = status
            self.db.update_step(self.step)

        if self.on_saved:
            self.on_saved()
        self.destroy()
