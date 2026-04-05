import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime

from .database import Database
from .models import Plan, PlanStep, StepStatus
from .ui.new_plan_dialog import NewPlanDialog
from .ui.step_editor_dialog import StepEditorDialog


class OrchestratorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("ClaudeCode Orchestrator")
        self.root.geometry("1280x800")
        self.root.minsize(1024, 768)

        self.db = Database()
        self.current_plan: Plan | None = None
        self.steps: list[PlanStep] = []

        self._build_ui()
        self._load_plans()

    # ── UI Construction ──────────────────────────────────────────

    def _build_ui(self):
        # Main horizontal paned window
        self.main_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.main_pane.pack(fill=tk.BOTH, expand=True)

        # Left pane – plan management
        left_frame = ttk.Frame(self.main_pane, width=300)
        self.main_pane.add(left_frame, weight=0)
        self._build_left_pane(left_frame)

        # Right pane – vertical split: step queue (top) + output (bottom)
        right_pane = ttk.PanedWindow(self.main_pane, orient=tk.VERTICAL)
        self.main_pane.add(right_pane, weight=1)

        top_frame = ttk.Frame(right_pane)
        right_pane.add(top_frame, weight=1)
        self._build_step_queue(top_frame)

        bottom_frame = ttk.Frame(right_pane)
        right_pane.add(bottom_frame, weight=1)
        self._build_output_viewer(bottom_frame)

        # Status bar
        self.status_var = tk.StringVar(value="No plan selected")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    def _build_left_pane(self, parent: ttk.Frame):
        ttk.Label(parent, text="Plans", font=("Segoe UI", 12, "bold")).pack(padx=5, pady=(5, 2), anchor=tk.W)

        # Plan listbox with scrollbar
        list_frame = ttk.Frame(parent)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL)
        self.plan_listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, exportselection=False)
        scrollbar.config(command=self.plan_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.plan_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.plan_listbox.bind("<<ListboxSelect>>", self._on_plan_selected)

        # Project path display
        path_frame = ttk.Frame(parent)
        path_frame.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(path_frame, text="Project Path:").pack(anchor=tk.W)
        self.path_var = tk.StringVar(value="")
        path_entry = ttk.Entry(path_frame, textvariable=self.path_var, state="readonly")
        path_entry.pack(fill=tk.X)

        ttk.Button(path_frame, text="Set Project Path", command=self._set_project_path).pack(fill=tk.X, pady=(2, 0))

        # Plan action buttons
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(btn_frame, text="New Plan", command=self._new_plan).pack(fill=tk.X, pady=1)
        ttk.Button(btn_frame, text="Delete Plan", command=self._delete_plan).pack(fill=tk.X, pady=1)
        ttk.Button(btn_frame, text="Import JSON", command=self._import_json).pack(fill=tk.X, pady=1)

    def _build_step_queue(self, parent: ttk.Frame):
        # Button bar
        btn_bar = ttk.Frame(parent)
        btn_bar.pack(fill=tk.X, padx=5, pady=2)
        for text, cmd in [
            ("Add Step", self._add_step),
            ("Edit Step", self._edit_step),
            ("Delete Step", self._delete_step),
            ("Move Up", self._move_step_up),
            ("Move Down", self._move_step_down),
            ("Run Queue", self._run_queue),
            ("Stop", self._stop_queue),
        ]:
            ttk.Button(btn_bar, text=text, command=cmd).pack(side=tk.LEFT, padx=2)

        # Treeview for steps
        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)

        columns = ("#", "Name", "Title", "Status", "Prompt")
        self.step_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")
        self.step_tree.heading("#", text="#")
        self.step_tree.heading("Name", text="Name")
        self.step_tree.heading("Title", text="Title")
        self.step_tree.heading("Status", text="Status")
        self.step_tree.heading("Prompt", text="Prompt")

        self.step_tree.column("#", width=40, stretch=False)
        self.step_tree.column("Name", width=120)
        self.step_tree.column("Title", width=200)
        self.step_tree.column("Status", width=80, stretch=False)
        self.step_tree.column("Prompt", width=300)

        tree_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.step_tree.yview)
        self.step_tree.configure(yscrollcommand=tree_scroll.set)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.step_tree.pack(fill=tk.BOTH, expand=True)

        self.step_tree.bind("<<TreeviewSelect>>", self._on_step_selected)
        self.step_tree.bind("<Double-1>", lambda e: self._edit_step())

    def _build_output_viewer(self, parent: ttk.Frame):
        ttk.Label(parent, text="Step Result", font=("Segoe UI", 10, "bold")).pack(padx=5, pady=(5, 2), anchor=tk.W)
        text_frame = ttk.Frame(parent)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        self.output_text = tk.Text(text_frame, wrap=tk.WORD, state=tk.DISABLED)
        out_scroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.output_text.yview)
        self.output_text.configure(yscrollcommand=out_scroll.set)
        out_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.output_text.pack(fill=tk.BOTH, expand=True)

    # ── Data Loading ─────────────────────────────────────────────

    def _load_plans(self):
        self.plan_listbox.delete(0, tk.END)
        self._plans = self.db.get_plans()
        for p in self._plans:
            created = p.created_at[:10] if p.created_at else ""
            self.plan_listbox.insert(tk.END, f"{p.name}  ({created})")

    def _load_steps(self):
        for item in self.step_tree.get_children():
            self.step_tree.delete(item)
        self.steps = []
        if not self.current_plan:
            return
        self.steps = self.db.get_steps_for_plan(self.current_plan.id)
        for s in self.steps:
            prompt_preview = (s.prompt[:60] + "…") if len(s.prompt) > 60 else s.prompt
            self.step_tree.insert("", tk.END, iid=s.id, values=(
                s.queue_position + 1, s.name, s.title, s.status.value, prompt_preview,
            ))

    def _update_status_bar(self):
        if not self.current_plan:
            self.status_var.set("No plan selected")
            return
        total = len(self.steps)
        done = sum(1 for s in self.steps if s.status == StepStatus.SUCCEEDED)
        self.status_var.set(
            f"Plan: {self.current_plan.name}  |  "
            f"Path: {self.current_plan.project_root or '(not set)'}  |  "
            f"Steps: {done}/{total} completed"
        )

    # ── Event Handlers ───────────────────────────────────────────

    def _on_plan_selected(self, event):
        sel = self.plan_listbox.curselection()
        if not sel:
            return
        self.current_plan = self._plans[sel[0]]
        self.path_var.set(self.current_plan.project_root)
        self._load_steps()
        self._set_output_text("No result yet")
        self._update_status_bar()

    def _on_step_selected(self, event):
        sel = self.step_tree.selection()
        if not sel:
            return
        step = next((s for s in self.steps if s.id == sel[0]), None)
        if step:
            self._set_output_text(step.result or "No result yet")

    # ── Plan Actions ─────────────────────────────────────────────

    def _new_plan(self):
        NewPlanDialog(self.root, self.db, on_saved=self._load_plans)

    def _delete_plan(self):
        if not self.current_plan:
            messagebox.showwarning("Delete Plan", "No plan selected.")
            return
        if not messagebox.askyesno("Delete Plan", f"Delete '{self.current_plan.name}'?"):
            return
        self.db.delete_plan(self.current_plan.id)
        self.current_plan = None
        self.path_var.set("")
        self._load_plans()
        self._load_steps()
        self._set_output_text("")
        self._update_status_bar()

    def _import_json(self):
        # Placeholder – will be implemented later
        messagebox.showinfo("Import JSON", "JSON import not yet implemented.")

    def _set_project_path(self):
        if not self.current_plan:
            messagebox.showwarning("Set Path", "No plan selected.")
            return
        path = filedialog.askdirectory(title="Select Project Root")
        if not path:
            return
        self.current_plan.project_root = path
        self.db.update_plan(self.current_plan)
        self.path_var.set(path)
        self._update_status_bar()

    # ── Step Actions (stubs) ─────────────────────────────────────

    def _add_step(self):
        if not self.current_plan:
            messagebox.showwarning("Add Step", "No plan selected.")
            return
        # Insert after the selected step, or at the end
        sel = self.step_tree.selection()
        if sel:
            idx = next((i for i, s in enumerate(self.steps) if s.id == sel[0]), len(self.steps))
            insert_pos = idx + 1
        else:
            insert_pos = len(self.steps)

        def _on_saved():
            # Reorder: shift steps at insert_pos+ forward, then reload
            all_steps = self.db.get_steps_for_plan(self.current_plan.id)
            all_steps.sort(key=lambda s: s.queue_position)
            self.db.reorder_steps(self.current_plan.id, [s.id for s in all_steps])
            self._load_steps()
            self._update_status_bar()

        StepEditorDialog(
            self.root, self.db, step=None,
            plan_id=self.current_plan.id,
            insert_position=insert_pos,
            on_saved=_on_saved,
        )

    def _edit_step(self):
        sel = self.step_tree.selection()
        if not sel:
            messagebox.showwarning("Edit Step", "No step selected.")
            return
        step = next((s for s in self.steps if s.id == sel[0]), None)
        if not step:
            return

        def _on_saved():
            self._load_steps()
            self._update_status_bar()

        StepEditorDialog(
            self.root, self.db, step=step,
            on_saved=_on_saved,
        )

    def _delete_step(self):
        sel = self.step_tree.selection()
        if not sel:
            messagebox.showwarning("Delete Step", "No step selected.")
            return
        step = next((s for s in self.steps if s.id == sel[0]), None)
        if not step:
            return
        if not messagebox.askyesno("Delete Step", f"Delete step '{step.name}'?"):
            return
        self.db.delete_step(step.id)
        # Reorder remaining steps
        if self.current_plan:
            remaining = [s for s in self.steps if s.id != step.id]
            self.db.reorder_steps(self.current_plan.id, [s.id for s in remaining])
        self._load_steps()
        self._update_status_bar()

    def _move_step_up(self):
        self._move_step(-1)

    def _move_step_down(self):
        self._move_step(1)

    def _move_step(self, direction: int):
        sel = self.step_tree.selection()
        if not sel or not self.current_plan:
            return
        idx = next((i for i, s in enumerate(self.steps) if s.id == sel[0]), None)
        if idx is None:
            return
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self.steps):
            return
        ids = [s.id for s in self.steps]
        ids[idx], ids[new_idx] = ids[new_idx], ids[idx]
        self.db.reorder_steps(self.current_plan.id, ids)
        self._load_steps()
        # Re-select the moved item
        moved_id = self.steps[new_idx].id if new_idx < len(self.steps) else None
        if moved_id:
            self.step_tree.selection_set(moved_id)

    def _run_queue(self):
        messagebox.showinfo("Run Queue", "Execution not yet implemented.")

    def _stop_queue(self):
        messagebox.showinfo("Stop", "Execution not yet implemented.")

    # ── Helpers ───────────────────────────────────────────────────

    def _set_output_text(self, text: str):
        self.output_text.config(state=tk.NORMAL)
        self.output_text.delete("1.0", tk.END)
        self.output_text.insert("1.0", text)
        self.output_text.config(state=tk.DISABLED)


def main():
    root = tk.Tk()
    OrchestratorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
