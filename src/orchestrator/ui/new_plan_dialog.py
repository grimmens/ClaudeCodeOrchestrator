import json
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from ..config import load_config
from ..database import Database
from ..models import Plan, PlanStep
from ..services.claude_runner import run_claude


class NewPlanDialog(tk.Toplevel):
    def __init__(self, parent: tk.Tk, db: Database, on_saved=None):
        super().__init__(parent)
        self.db = db
        self.on_saved = on_saved
        self.title("New Plan")
        self.geometry("800x700")
        self.transient(parent)
        self.grab_set()

        self._preview_steps: list[dict] = []
        self._build_ui()

    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # Plan name
        ttk.Label(self, text="Plan Name:").pack(anchor=tk.W, **pad)
        self.name_var = tk.StringVar()
        ttk.Entry(self, textvariable=self.name_var).pack(fill=tk.X, **pad)

        # Project path
        path_frame = ttk.Frame(self)
        path_frame.pack(fill=tk.X, **pad)
        ttk.Label(path_frame, text="Project Path (working directory):").pack(anchor=tk.W)
        inner = ttk.Frame(path_frame)
        inner.pack(fill=tk.X)
        self.path_var = tk.StringVar()
        ttk.Entry(inner, textvariable=self.path_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(inner, text="Browse", command=self._browse_path).pack(side=tk.LEFT, padx=(4, 0))

        # Description
        ttk.Label(self, text="Plan Description:").pack(anchor=tk.W, **pad)
        self.desc_text = tk.Text(self, height=8, wrap=tk.WORD)
        self.desc_text.pack(fill=tk.X, **pad)

        # Ask Claude button
        self.split_btn = ttk.Button(self, text="Ask Claude to Split into Steps", command=self._ask_claude)
        self.split_btn.pack(**pad)

        # Progress label (hidden by default)
        self.progress_var = tk.StringVar()
        self.progress_label = ttk.Label(self, textvariable=self.progress_var, foreground="blue")
        self.progress_label.pack(**pad)

        # Preview treeview
        ttk.Label(self, text="Step Preview:").pack(anchor=tk.W, **pad)
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill=tk.BOTH, expand=True, **pad)

        columns = ("Name", "Title", "Prompt")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("Name", text="Name")
        self.tree.heading("Title", text="Title")
        self.tree.heading("Prompt", text="Prompt")
        self.tree.column("Name", width=120)
        self.tree.column("Title", width=200)
        self.tree.column("Prompt", width=400)
        scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(fill=tk.BOTH, expand=True)

        # Step action buttons
        step_btn_frame = ttk.Frame(self)
        step_btn_frame.pack(fill=tk.X, **pad)
        ttk.Button(step_btn_frame, text="Add Step", command=self._add_step_manual).pack(side=tk.LEFT, padx=2)
        ttk.Button(step_btn_frame, text="Edit Selected", command=self._edit_selected_step).pack(side=tk.LEFT, padx=2)
        ttk.Button(step_btn_frame, text="Delete Selected", command=self._delete_selected_step).pack(side=tk.LEFT, padx=2)

        self.tree.bind("<Double-1>", lambda e: self._edit_selected_step())

        # Save button
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=8, pady=10)
        ttk.Button(btn_frame, text="Save Plan", command=self._save_plan).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=4)

    def _browse_path(self):
        path = filedialog.askdirectory(title="Select Project Root", parent=self)
        if path:
            self.path_var.set(path)

    def _ask_claude(self):
        description = self.desc_text.get("1.0", tk.END).strip()
        working_dir = self.path_var.get().strip()
        if not description:
            messagebox.showwarning("Missing Description", "Please enter a plan description.", parent=self)
            return
        if not working_dir:
            messagebox.showwarning("Missing Path", "Please set a project path.", parent=self)
            return

        self.split_btn.config(state=tk.DISABLED)
        self.progress_var.set("Asking Claude to split into steps...")

        def _run():
            config = load_config()
            planner_prompt = (
                "You are a project planner. Break the following goal into small, atomic, "
                "sequential steps for a coding agent. Return ONLY a JSON array where each "
                "element has: name (kebab-case), title (one-line), prompt (detailed instructions). "
                "No markdown fences.\n\n"
                f"{description}"
            )
            exit_code, stdout, stderr = run_claude(planner_prompt, working_dir, config)
            self.after(0, lambda: self._on_claude_done(exit_code, stdout, stderr))

        threading.Thread(target=_run, daemon=True).start()

    def _on_claude_done(self, exit_code: int, stdout: str, stderr: str):
        self.split_btn.config(state=tk.NORMAL)
        self.progress_var.set("")

        if exit_code != 0:
            messagebox.showerror("Claude Error", f"Claude exited with code {exit_code}.\n\n{stderr}", parent=self)
            return

        try:
            steps = json.loads(stdout.strip())
            if not isinstance(steps, list):
                raise ValueError("Expected a JSON array")
        except (json.JSONDecodeError, ValueError) as e:
            messagebox.showerror("Parse Error", f"Failed to parse Claude's response:\n{e}\n\nRaw output:\n{stdout[:500]}", parent=self)
            return

        self._preview_steps = steps
        self._refresh_tree()

    def _refresh_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for i, s in enumerate(self._preview_steps):
            prompt_preview = s.get("prompt", "")
            if len(prompt_preview) > 60:
                prompt_preview = prompt_preview[:60] + "..."
            self.tree.insert("", tk.END, iid=str(i), values=(
                s.get("name", ""), s.get("title", ""), prompt_preview
            ))

    def _add_step_manual(self):
        dlg = _MiniStepDialog(self)
        self.wait_window(dlg)
        if dlg.result:
            self._preview_steps.append(dlg.result)
            self._refresh_tree()

    def _edit_selected_step(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Edit Step", "No step selected.", parent=self)
            return
        idx = int(sel[0])
        existing = self._preview_steps[idx]
        dlg = _MiniStepDialog(self, existing=existing)
        self.wait_window(dlg)
        if dlg.result:
            self._preview_steps[idx] = dlg.result
            self._refresh_tree()

    def _delete_selected_step(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        del self._preview_steps[idx]
        self._refresh_tree()

    def _save_plan(self):
        name = self.name_var.get().strip()
        project_root = self.path_var.get().strip()
        if not name:
            messagebox.showwarning("Missing Name", "Please enter a plan name.", parent=self)
            return
        if not project_root:
            messagebox.showwarning("Missing Path", "Please set a project path.", parent=self)
            return

        plan = Plan(name=name, project_root=project_root)
        self.db.create_plan(plan)

        for i, s in enumerate(self._preview_steps):
            step = PlanStep(
                plan_id=plan.id,
                queue_position=i,
                name=s.get("name", f"step-{i+1}"),
                title=s.get("title", ""),
                prompt=s.get("prompt", ""),
            )
            self.db.create_step(step)

        if self.on_saved:
            self.on_saved()
        self.destroy()


class _MiniStepDialog(tk.Toplevel):
    """Small dialog to add or edit a step."""

    def __init__(self, parent, existing: dict = None):
        super().__init__(parent)
        self.title("Edit Step" if existing else "Add Step")
        self.geometry("500x400")
        self.transient(parent)
        self.grab_set()
        self.result = None

        pad = {"padx": 8, "pady": 4}
        ttk.Label(self, text="Name (kebab-case):").pack(anchor=tk.W, **pad)
        self.name_var = tk.StringVar(value=existing.get("name", "") if existing else "")
        ttk.Entry(self, textvariable=self.name_var).pack(fill=tk.X, **pad)

        ttk.Label(self, text="Title:").pack(anchor=tk.W, **pad)
        self.title_var = tk.StringVar(value=existing.get("title", "") if existing else "")
        ttk.Entry(self, textvariable=self.title_var).pack(fill=tk.X, **pad)

        ttk.Label(self, text="Prompt:").pack(anchor=tk.W, **pad)
        self.prompt_text = tk.Text(self, height=10, wrap=tk.WORD)
        self.prompt_text.pack(fill=tk.BOTH, expand=True, **pad)
        if existing and existing.get("prompt"):
            self.prompt_text.insert("1.0", existing["prompt"])

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, **pad, pady=(4, 8))
        ttk.Button(btn_frame, text="Save", command=self._ok).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=4)

    def _ok(self):
        name = self.name_var.get().strip()
        title = self.title_var.get().strip()
        prompt = self.prompt_text.get("1.0", tk.END).strip()
        if not name:
            messagebox.showwarning("Missing Name", "Please enter a step name.", parent=self)
            return
        self.result = {"name": name, "title": title, "prompt": prompt}
        self.destroy()
