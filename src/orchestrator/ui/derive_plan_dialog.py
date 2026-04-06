import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from ..config import load_config
from ..database import Database
from ..models import Plan, PlanStep, StepStatus
from ..services.claude_runner import run_claude
from ..services.json_parser import extract_json_steps
from ..services.context_builder import build_history_context


class DerivePlanDialog(tk.Toplevel):
    """Dialog for creating a new plan derived from an existing plan."""

    def __init__(self, parent: tk.Tk, db: Database, plans: list[Plan],
                 selected_plan_id: str | None = None, on_saved=None):
        super().__init__(parent)
        self.db = db
        self.plans = plans
        self.on_saved = on_saved
        self._preview_steps: list[dict] = []

        self.title("New Plan from Existing")
        self.geometry("950x800")
        self.transient(parent)
        self.grab_set()

        self._build_ui(selected_plan_id)

    def _build_ui(self, selected_plan_id: str | None):
        pad = {"padx": 8, "pady": 4}

        # Source plan selector
        src_frame = ttk.LabelFrame(self, text="Source Plan")
        src_frame.pack(fill=tk.X, **pad)

        row = ttk.Frame(src_frame)
        row.pack(fill=tk.X, padx=4, pady=4)
        ttk.Label(row, text="Source:").pack(side=tk.LEFT)
        self._plan_map = {p.name: p for p in self.plans}
        plan_names = [p.name for p in self.plans]
        self.source_var = tk.StringVar()
        self.source_combo = ttk.Combobox(row, textvariable=self.source_var,
                                         values=plan_names, state="readonly", width=40)
        self.source_combo.pack(side=tk.LEFT, padx=(4, 0))
        self.source_combo.bind("<<ComboboxSelected>>", lambda e: self._update_source_summary())

        # Select default
        if selected_plan_id:
            for p in self.plans:
                if p.id == selected_plan_id:
                    self.source_var.set(p.name)
                    break
        elif plan_names:
            self.source_var.set(plan_names[0])

        # Source summary
        self.summary_var = tk.StringVar(value="")
        ttk.Label(src_frame, textvariable=self.summary_var, foreground="gray").pack(
            anchor=tk.W, padx=4, pady=(0, 4))

        # New plan name
        name_frame = ttk.LabelFrame(self, text="New Plan")
        name_frame.pack(fill=tk.X, **pad)

        row2 = ttk.Frame(name_frame)
        row2.pack(fill=tk.X, padx=4, pady=4)
        ttk.Label(row2, text="Name:").pack(side=tk.LEFT)
        self.name_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.name_var, width=50).pack(side=tk.LEFT, padx=(4, 0))

        row3 = ttk.Frame(name_frame)
        row3.pack(fill=tk.X, padx=4, pady=4)
        ttk.Label(row3, text="Project Path:").pack(side=tk.LEFT)
        self.path_var = tk.StringVar()
        ttk.Entry(row3, textvariable=self.path_var, width=40).pack(side=tk.LEFT, padx=(4, 4))
        ttk.Button(row3, text="Browse...", command=self._browse_path).pack(side=tk.LEFT)

        # Options
        opts_frame = ttk.LabelFrame(self, text="Options")
        opts_frame.pack(fill=tk.X, **pad)

        self.copy_ref_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts_frame, text="Copy succeeded steps as reference (read-only)",
                        variable=self.copy_ref_var).pack(anchor=tk.W, padx=4, pady=2)

        self.link_history_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts_frame, text="Include full history from source plan",
                        variable=self.link_history_var).pack(anchor=tk.W, padx=4, pady=2)

        # Goals
        ttk.Label(self, text="New Goals:").pack(anchor=tk.W, **pad)
        self.goals_text = tk.Text(self, height=5, wrap=tk.WORD)
        self.goals_text.pack(fill=tk.X, **pad)

        # Generate button
        btn_row = ttk.Frame(self)
        btn_row.pack(fill=tk.X, **pad)
        self.generate_btn = ttk.Button(btn_row, text="Generate Steps", command=self._generate_steps)
        self.generate_btn.pack(side=tk.LEFT, padx=2)
        self.progress_var = tk.StringVar()
        ttk.Label(btn_row, textvariable=self.progress_var, foreground="blue").pack(side=tk.LEFT, padx=8)

        # Step preview
        ttk.Label(self, text="New Steps Preview:").pack(anchor=tk.W, **pad)
        preview_frame = ttk.Frame(self)
        preview_frame.pack(fill=tk.BOTH, expand=True, **pad)

        preview_cols = ("Name", "Title", "Prompt")
        self.preview_tree = ttk.Treeview(preview_frame, columns=preview_cols,
                                         show="headings", selectmode="browse")
        self.preview_tree.heading("Name", text="Name")
        self.preview_tree.heading("Title", text="Title")
        self.preview_tree.heading("Prompt", text="Prompt")
        self.preview_tree.column("Name", width=120)
        self.preview_tree.column("Title", width=200)
        self.preview_tree.column("Prompt", width=400)
        p_scroll = ttk.Scrollbar(preview_frame, orient=tk.VERTICAL, command=self.preview_tree.yview)
        self.preview_tree.configure(yscrollcommand=p_scroll.set)
        p_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.preview_tree.pack(fill=tk.BOTH, expand=True)

        # Bottom buttons
        bottom = ttk.Frame(self)
        bottom.pack(fill=tk.X, padx=8, pady=10)
        ttk.Button(bottom, text="Create Plan", command=self._create_plan).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bottom, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=4)

        # Initialize summary
        self._update_source_summary()

    def _get_source_plan(self) -> Plan | None:
        name = self.source_var.get()
        return self._plan_map.get(name)

    def _update_source_summary(self):
        plan = self._get_source_plan()
        if not plan:
            self.summary_var.set("")
            self.name_var.set("")
            self.path_var.set("")
            return

        steps = self.db.get_steps_for_plan(plan.id)
        status_counts: dict[str, int] = {}
        for s in steps:
            status_counts[s.status.value] = status_counts.get(s.status.value, 0) + 1
        breakdown = ", ".join(f"{v} {k}" for k, v in status_counts.items())

        snapshots = self.db.get_history_for_plan(plan.id)
        last_snap = snapshots[-1].snapshot_at[:10] if snapshots else "none"

        self.summary_var.set(
            f"{len(steps)} steps ({breakdown}) | Last snapshot: {last_snap}"
        )
        self.name_var.set(f"{plan.name} - continued")
        self.path_var.set(plan.project_root or "")

    def _browse_path(self):
        path = filedialog.askdirectory(title="Select Project Root")
        if path:
            self.path_var.set(path)

    def _build_source_summary(self, plan: Plan) -> str:
        """Build text summary of source plan steps for Claude prompt."""
        steps = self.db.get_steps_for_plan(plan.id)
        lines = []
        for s in steps:
            result_summary = ""
            if s.result:
                result_summary = s.result[:200].replace("\n", " ")
                if len(s.result) > 200:
                    result_summary += "..."
            lines.append(
                f"Step {s.queue_position + 1} ({s.name}): {s.title} [{s.status.value}]"
                + (f"\n  Result: {result_summary}" if result_summary else "")
            )
        return "\n".join(lines)

    def _generate_steps(self):
        plan = self._get_source_plan()
        if not plan:
            messagebox.showwarning("Generate", "No source plan selected.", parent=self)
            return
        goals = self.goals_text.get("1.0", tk.END).strip()
        if not goals:
            messagebox.showwarning("Generate", "Please describe the new goals.", parent=self)
            return

        working_dir = self.path_var.get().strip() or plan.project_root
        if not working_dir:
            messagebox.showwarning("Generate", "No project path set.", parent=self)
            return

        self.generate_btn.config(state=tk.DISABLED)
        self.progress_var.set("Asking Claude to generate steps...")

        def _run():
            config = load_config()
            source_summary = self._build_source_summary(plan)
            history_context = build_history_context(self.db, plan.id)

            prompt = (
                "You are a project planner. A previous plan has been completed (or partially completed). "
                "The user wants to create a NEW plan that builds upon this previous work.\n\n"
                f"PREVIOUS PLAN: {plan.name}\n"
                f"PREVIOUS STEPS:\n{source_summary}\n\n"
            )
            if history_context:
                prompt += f"{history_context}\n"
            prompt += (
                f"NEW GOALS:\n{goals}\n\n"
                "Generate steps for the new plan that build upon the previous work. "
                "These should be NEW steps only — the previous completed steps will be included "
                "as read-only references. "
                "Return ONLY a JSON array where each element has: name (kebab-case), title (one-line), "
                "prompt (detailed instructions that reference prior step results where relevant). "
                "No markdown fences."
            )

            exit_code, stdout, stderr = run_claude(prompt, working_dir, config)
            self.after(0, lambda: self._on_claude_done(exit_code, stdout, stderr))

        threading.Thread(target=_run, daemon=True).start()

    def _on_claude_done(self, exit_code: int, stdout: str, stderr: str):
        self.generate_btn.config(state=tk.NORMAL)
        self.progress_var.set("")

        if exit_code != 0:
            messagebox.showerror("Claude Error",
                                 f"Claude exited with code {exit_code}.\n\n{stderr}", parent=self)
            return

        try:
            steps, warnings = extract_json_steps(stdout)
        except ValueError as e:
            messagebox.showerror("Parse Error", str(e), parent=self)
            return

        if warnings:
            self.progress_var.set("Parsed with fixups: " + "; ".join(warnings))

        self._preview_steps = steps
        self._refresh_preview()

    def _refresh_preview(self):
        for item in self.preview_tree.get_children():
            self.preview_tree.delete(item)
        for i, s in enumerate(self._preview_steps):
            prompt_preview = s.get("prompt", "")
            if len(prompt_preview) > 60:
                prompt_preview = prompt_preview[:60] + "..."
            self.preview_tree.insert("", tk.END, iid=str(i), values=(
                s.get("name", ""), s.get("title", ""), prompt_preview,
            ))

    def _create_plan(self):
        plan_name = self.name_var.get().strip()
        if not plan_name:
            messagebox.showwarning("Create Plan", "Please enter a plan name.", parent=self)
            return
        project_path = self.path_var.get().strip()
        if not project_path:
            messagebox.showwarning("Create Plan", "Please set a project path.", parent=self)
            return
        if not self._preview_steps:
            messagebox.showwarning("Create Plan", "No steps to create. Generate steps first.", parent=self)
            return

        source_plan = self._get_source_plan()
        parent_id = source_plan.id if source_plan and self.link_history_var.get() else None

        new_plan = Plan(
            name=plan_name,
            project_root=project_path,
            parent_plan_id=parent_id,
        )
        self.db.create_plan(new_plan)

        # Copy reference steps from source plan if requested
        ref_offset = 0
        if source_plan and self.copy_ref_var.get():
            source_steps = self.db.get_steps_for_plan(source_plan.id)
            succeeded = [s for s in source_steps if s.status == StepStatus.SUCCEEDED]
            for i, s in enumerate(succeeded):
                ref_step = PlanStep(
                    plan_id=new_plan.id,
                    queue_position=i,
                    name=s.name,
                    title=s.title,
                    prompt=s.prompt,
                    description=s.description,
                    result=s.result,
                    status=StepStatus.REFERENCE,
                )
                self.db.create_step(ref_step)
            ref_offset = len(succeeded)

        # Add new generated steps
        for i, s in enumerate(self._preview_steps):
            step = PlanStep(
                plan_id=new_plan.id,
                queue_position=ref_offset + i,
                name=s.get("name", f"step-{ref_offset + i + 1}"),
                title=s.get("title", ""),
                prompt=s.get("prompt", ""),
            )
            self.db.create_step(step)

        if self.on_saved:
            self.on_saved(new_plan.id)
        self.destroy()
