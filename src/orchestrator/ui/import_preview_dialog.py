import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Callable, List, Dict, Optional

from ..database import Database
from ..models import Plan, PlanStep


class ImportPreviewDialog:
    """Preview and confirm import of steps from a JSON file."""

    def __init__(self, parent: tk.Tk, db: Database, steps_data: List[Dict],
                 on_saved: Optional[Callable] = None):
        self.db = db
        self.steps_data = steps_data
        self.on_saved = on_saved

        self.win = tk.Toplevel(parent)
        self.win.title("Import Plan - Preview")
        self.win.geometry("700x500")
        self.win.transient(parent)
        self.win.grab_set()

        self._build_ui()

    def _build_ui(self):
        # Plan name
        name_frame = ttk.Frame(self.win)
        name_frame.pack(fill=tk.X, padx=10, pady=(10, 5))
        ttk.Label(name_frame, text="Plan Name:").pack(side=tk.LEFT, padx=(0, 5))
        self.name_var = tk.StringVar(value="Imported Plan")
        ttk.Entry(name_frame, textvariable=self.name_var, width=40).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Project path
        path_frame = ttk.Frame(self.win)
        path_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(path_frame, text="Project Path:").pack(side=tk.LEFT, padx=(0, 5))
        self.path_var = tk.StringVar()
        ttk.Entry(path_frame, textvariable=self.path_var, width=40).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(path_frame, text="Browse", command=self._browse_path).pack(side=tk.LEFT)

        # Steps preview
        ttk.Label(self.win, text=f"Steps to import ({len(self.steps_data)}):").pack(
            padx=10, pady=(10, 2), anchor=tk.W)

        tree_frame = ttk.Frame(self.win)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=2)

        columns = ("#", "Name", "Title", "Prompt")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("#", text="#")
        self.tree.heading("Name", text="Name")
        self.tree.heading("Title", text="Title")
        self.tree.heading("Prompt", text="Prompt")
        self.tree.column("#", width=40, stretch=False)
        self.tree.column("Name", width=120)
        self.tree.column("Title", width=200)
        self.tree.column("Prompt", width=300)

        scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(fill=tk.BOTH, expand=True)

        for i, s in enumerate(self.steps_data):
            prompt = s.get("prompt", "")
            prompt_preview = (prompt[:60] + "\u2026") if len(prompt) > 60 else prompt
            self.tree.insert("", tk.END, values=(
                i + 1,
                s.get("name", s.get("step", "")),
                s.get("title", ""),
                prompt_preview,
            ))

        # Buttons
        btn_frame = ttk.Frame(self.win)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        ttk.Button(btn_frame, text="Import", command=self._do_import).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.win.destroy).pack(side=tk.RIGHT, padx=5)

    def _browse_path(self):
        path = filedialog.askdirectory(title="Select Project Root")
        if path:
            self.path_var.set(path)

    def _do_import(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Import", "Please enter a plan name.", parent=self.win)
            return
        project_path = self.path_var.get().strip()
        if not project_path:
            messagebox.showwarning("Import", "Please select a project path.", parent=self.win)
            return

        plan = Plan(name=name, project_root=project_path)
        self.db.create_plan(plan)

        for i, s in enumerate(self.steps_data):
            step = PlanStep(
                plan_id=plan.id,
                queue_position=i,
                name=s.get("name", s.get("step", f"step-{i+1}")),
                title=s.get("title", ""),
                prompt=s.get("prompt", ""),
                description=s.get("description", None),
            )
            self.db.create_step(step)

        self.win.destroy()
        if self.on_saved:
            self.on_saved()
