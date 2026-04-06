import json
import re
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Optional

from ..database import Database
from ..models import Plan, PlanStep, StepStatus


class SaveAsTemplateDialog(tk.Toplevel):
    """Dialog for saving a completed plan as a reusable template."""

    def __init__(self, parent: tk.Tk, db: Database, plan_id: str, on_saved=None):
        super().__init__(parent)
        self.db = db
        self.on_saved = on_saved
        self.plan = db.get_plan(plan_id)
        self.steps = db.get_steps_for_plan(plan_id)

        self.title("Save Plan as Template")
        self.geometry("900x700")
        self.transient(parent)
        self.grab_set()

        self._build_ui()

    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # Template name and description
        info_frame = ttk.LabelFrame(self, text="Template Info")
        info_frame.pack(fill=tk.X, **pad)

        row1 = ttk.Frame(info_frame)
        row1.pack(fill=tk.X, padx=4, pady=4)
        ttk.Label(row1, text="Template Name:").pack(side=tk.LEFT)
        self.name_var = tk.StringVar(value=f"{self.plan.name} Template")
        ttk.Entry(row1, textvariable=self.name_var, width=50).pack(side=tk.LEFT, padx=(4, 0))

        ttk.Label(info_frame, text="Description:").pack(anchor=tk.W, padx=4)
        self.desc_text = tk.Text(info_frame, height=3, wrap=tk.WORD)
        self.desc_text.pack(fill=tk.X, padx=4, pady=(0, 4))

        # Placeholder hint
        hint = ttk.Label(self, text="Tip: Use placeholders like {project_name}, {language} in prompts to make the template generic.",
                         foreground="gray")
        hint.pack(anchor=tk.W, **pad)

        # Steps treeview
        ttk.Label(self, text="Template Steps (double-click to edit prompt):").pack(anchor=tk.W, **pad)
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill=tk.BOTH, expand=True, **pad)

        columns = ("Name", "Title", "Prompt Preview")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("Name", text="Name")
        self.tree.heading("Title", text="Title")
        self.tree.heading("Prompt Preview", text="Prompt Preview")
        self.tree.column("Name", width=130)
        self.tree.column("Title", width=200)
        self.tree.column("Prompt Preview", width=450)
        scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<Double-1>", lambda e: self._edit_step_prompt())

        # Build template step data (strip results, reset status)
        self._template_steps: list[dict] = []
        for s in self.steps:
            if s.status == StepStatus.REFERENCE:
                continue  # Skip reference-only steps
            self._template_steps.append({
                "name": s.name,
                "title": s.title,
                "prompt": s.prompt,
                "description": s.description or "",
            })
        self._refresh_tree()

        # Step action buttons
        step_btn_frame = ttk.Frame(self)
        step_btn_frame.pack(fill=tk.X, **pad)
        ttk.Button(step_btn_frame, text="Edit Selected", command=self._edit_step_prompt).pack(side=tk.LEFT, padx=2)
        ttk.Button(step_btn_frame, text="Delete Selected", command=self._delete_selected).pack(side=tk.LEFT, padx=2)

        # Save / Cancel
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=8, pady=10)
        ttk.Button(btn_frame, text="Save Template", command=self._save).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=4)

    def _refresh_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for i, s in enumerate(self._template_steps):
            prompt_preview = s["prompt"]
            if len(prompt_preview) > 80:
                prompt_preview = prompt_preview[:80] + "..."
            self.tree.insert("", tk.END, iid=str(i), values=(
                s["name"], s["title"], prompt_preview
            ))

    def _edit_step_prompt(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Edit Step", "No step selected.", parent=self)
            return
        idx = int(sel[0])
        existing = self._template_steps[idx]
        dlg = _TemplateStepEditor(self, existing)
        self.wait_window(dlg)
        if dlg.result:
            self._template_steps[idx] = dlg.result
            self._refresh_tree()

    def _delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        del self._template_steps[idx]
        self._refresh_tree()

    def _save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Missing Name", "Please enter a template name.", parent=self)
            return
        if not self._template_steps:
            messagebox.showwarning("No Steps", "Template must have at least one step.", parent=self)
            return

        description = self.desc_text.get("1.0", tk.END).strip() or None
        self.db.create_template(
            name=name,
            description=description,
            steps_json=json.dumps(self._template_steps),
            created_from_plan_id=self.plan.id,
        )
        if self.on_saved:
            self.on_saved()
        self.destroy()


class CreateFromTemplateDialog(tk.Toplevel):
    """Dialog for creating a new plan from a saved template."""

    def __init__(self, parent: tk.Tk, db: Database, on_saved=None):
        super().__init__(parent)
        self.db = db
        self.on_saved = on_saved
        self._templates = db.get_templates()
        self._selected_template = None
        self._template_steps: list[dict] = []
        self._placeholders: list[str] = []

        self.title("New Plan from Template")
        self.geometry("900x750")
        self.transient(parent)
        self.grab_set()

        self._build_ui()

    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        if not self._templates:
            ttk.Label(self, text="No templates saved yet. Save a completed plan as a template first.").pack(**pad)
            ttk.Button(self, text="Close", command=self.destroy).pack(**pad)
            return

        # Template selector
        sel_frame = ttk.LabelFrame(self, text="Select Template")
        sel_frame.pack(fill=tk.X, **pad)

        row = ttk.Frame(sel_frame)
        row.pack(fill=tk.X, padx=4, pady=4)
        ttk.Label(row, text="Template:").pack(side=tk.LEFT)
        self._template_map = {t["name"]: t for t in self._templates}
        template_names = [t["name"] for t in self._templates]
        self.template_var = tk.StringVar()
        self.template_combo = ttk.Combobox(row, textvariable=self.template_var,
                                            values=template_names, state="readonly", width=50)
        self.template_combo.pack(side=tk.LEFT, padx=(4, 0))
        self.template_combo.bind("<<ComboboxSelected>>", lambda e: self._on_template_selected())

        self.template_desc_var = tk.StringVar()
        ttk.Label(sel_frame, textvariable=self.template_desc_var, foreground="gray").pack(
            anchor=tk.W, padx=4, pady=(0, 4))

        # Delete template button
        ttk.Button(sel_frame, text="Delete Template", command=self._delete_template).pack(
            anchor=tk.W, padx=4, pady=(0, 4))

        # New plan info
        plan_frame = ttk.LabelFrame(self, text="New Plan")
        plan_frame.pack(fill=tk.X, **pad)

        row2 = ttk.Frame(plan_frame)
        row2.pack(fill=tk.X, padx=4, pady=4)
        ttk.Label(row2, text="Plan Name:").pack(side=tk.LEFT)
        self.name_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.name_var, width=50).pack(side=tk.LEFT, padx=(4, 0))

        row3 = ttk.Frame(plan_frame)
        row3.pack(fill=tk.X, padx=4, pady=4)
        ttk.Label(row3, text="Project Path:").pack(side=tk.LEFT)
        self.path_var = tk.StringVar()
        ttk.Entry(row3, textvariable=self.path_var, width=40).pack(side=tk.LEFT, padx=(4, 4))
        ttk.Button(row3, text="Browse...", command=self._browse_path).pack(side=tk.LEFT)

        # Link parent plan option
        self.link_parent_var = tk.BooleanVar(value=False)
        self.link_parent_check = ttk.Checkbutton(plan_frame,
            text="Link to source plan for history continuity",
            variable=self.link_parent_var)
        self.link_parent_check.pack(anchor=tk.W, padx=4, pady=(0, 4))

        # Placeholder values
        self.placeholder_frame = ttk.LabelFrame(self, text="Placeholder Values")
        self.placeholder_frame.pack(fill=tk.X, **pad)
        self._placeholder_entries: dict[str, tk.StringVar] = {}
        self._placeholder_inner = ttk.Frame(self.placeholder_frame)
        self._placeholder_inner.pack(fill=tk.X, padx=4, pady=4)
        ttk.Label(self._placeholder_inner, text="Select a template to see placeholders.",
                  foreground="gray").pack(anchor=tk.W)

        # Step preview
        ttk.Label(self, text="Steps Preview:").pack(anchor=tk.W, **pad)
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill=tk.BOTH, expand=True, **pad)

        columns = ("Name", "Title", "Prompt Preview")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("Name", text="Name")
        self.tree.heading("Title", text="Title")
        self.tree.heading("Prompt Preview", text="Prompt Preview")
        self.tree.column("Name", width=130)
        self.tree.column("Title", width=200)
        self.tree.column("Prompt Preview", width=450)
        scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(fill=tk.BOTH, expand=True)

        # Save / Cancel
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=8, pady=10)
        ttk.Button(btn_frame, text="Create Plan", command=self._create_plan).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=4)

        # Auto-select first template
        if self._templates:
            self.template_var.set(self._templates[0]["name"])
            self._on_template_selected()

    def _browse_path(self):
        path = filedialog.askdirectory(title="Select Project Root", parent=self)
        if path:
            self.path_var.set(path)

    def _on_template_selected(self):
        name = self.template_var.get()
        tmpl = self._template_map.get(name)
        if not tmpl:
            return
        self._selected_template = tmpl
        self._template_steps = json.loads(tmpl["steps_json"])

        # Show description
        desc = tmpl.get("description") or "No description"
        step_count = len(self._template_steps)
        self.template_desc_var.set(f"{desc}  ({step_count} steps)")

        # Auto-fill plan name
        self.name_var.set(f"{tmpl['name'].replace(' Template', '')} - new")

        # Enable/disable parent link
        source_plan_id = tmpl.get("created_from_plan_id")
        if source_plan_id and self.db.get_plan(source_plan_id):
            self.link_parent_check.config(state=tk.NORMAL)
            self.link_parent_var.set(True)
        else:
            self.link_parent_check.config(state=tk.DISABLED)
            self.link_parent_var.set(False)

        # Detect placeholders across all step prompts
        self._detect_placeholders()
        self._build_placeholder_ui()
        self._refresh_tree()

    def _detect_placeholders(self):
        """Find all {placeholder} patterns in step prompts."""
        found: set[str] = set()
        for s in self._template_steps:
            matches = re.findall(r'\{(\w+)\}', s.get("prompt", ""))
            found.update(matches)
            matches = re.findall(r'\{(\w+)\}', s.get("title", ""))
            found.update(matches)
        self._placeholders = sorted(found)

    def _build_placeholder_ui(self):
        for widget in self._placeholder_inner.winfo_children():
            widget.destroy()
        self._placeholder_entries.clear()

        if not self._placeholders:
            ttk.Label(self._placeholder_inner, text="No placeholders found in this template.",
                      foreground="gray").pack(anchor=tk.W)
            return

        for ph in self._placeholders:
            row = ttk.Frame(self._placeholder_inner)
            row.pack(fill=tk.X, pady=1)
            ttk.Label(row, text=f"{{{ph}}}:", width=20).pack(side=tk.LEFT)
            var = tk.StringVar()
            ttk.Entry(row, textvariable=var, width=40).pack(side=tk.LEFT, padx=(4, 0))
            self._placeholder_entries[ph] = var

    def _get_resolved_steps(self) -> list[dict]:
        """Return steps with placeholders replaced by user values."""
        replacements = {ph: var.get() for ph, var in self._placeholder_entries.items()}
        resolved = []
        for s in self._template_steps:
            step = dict(s)
            for key in ("name", "title", "prompt", "description"):
                val = step.get(key, "")
                if val:
                    for ph, replacement in replacements.items():
                        val = val.replace(f"{{{ph}}}", replacement)
                    step[key] = val
            resolved.append(step)
        return resolved

    def _refresh_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for i, s in enumerate(self._template_steps):
            prompt_preview = s.get("prompt", "")
            if len(prompt_preview) > 80:
                prompt_preview = prompt_preview[:80] + "..."
            self.tree.insert("", tk.END, iid=str(i), values=(
                s.get("name", ""), s.get("title", ""), prompt_preview
            ))

    def _delete_template(self):
        if not self._selected_template:
            messagebox.showwarning("Delete Template", "No template selected.", parent=self)
            return
        if not messagebox.askyesno("Delete Template",
                                    f"Delete template '{self._selected_template['name']}'?",
                                    parent=self):
            return
        self.db.delete_template(self._selected_template["id"])
        self._templates = self.db.get_templates()
        self._template_map = {t["name"]: t for t in self._templates}
        template_names = [t["name"] for t in self._templates]
        self.template_combo.config(values=template_names)
        if template_names:
            self.template_var.set(template_names[0])
            self._on_template_selected()
        else:
            self.template_var.set("")
            self._selected_template = None
            self._template_steps = []
            self._refresh_tree()

    def _create_plan(self):
        name = self.name_var.get().strip()
        project_root = self.path_var.get().strip()
        if not name:
            messagebox.showwarning("Missing Name", "Please enter a plan name.", parent=self)
            return
        if not project_root:
            messagebox.showwarning("Missing Path", "Please set a project path.", parent=self)
            return
        if not self._template_steps:
            messagebox.showwarning("No Template", "Please select a template.", parent=self)
            return

        # Determine parent link
        parent_plan_id = None
        if self.link_parent_var.get() and self._selected_template:
            source_id = self._selected_template.get("created_from_plan_id")
            if source_id and self.db.get_plan(source_id):
                parent_plan_id = source_id

        plan = Plan(name=name, project_root=project_root, parent_plan_id=parent_plan_id)
        self.db.create_plan(plan)

        resolved = self._get_resolved_steps()
        for i, s in enumerate(resolved):
            step = PlanStep(
                plan_id=plan.id,
                queue_position=i,
                name=s.get("name", f"step-{i+1}"),
                title=s.get("title", ""),
                prompt=s.get("prompt", ""),
                description=s.get("description", "") or None,
            )
            self.db.create_step(step)

        if self.on_saved:
            self.on_saved(plan.id)
        self.destroy()


class _TemplateStepEditor(tk.Toplevel):
    """Dialog for editing a template step's prompt."""

    def __init__(self, parent, existing: dict):
        super().__init__(parent)
        self.title("Edit Template Step")
        self.geometry("600x450")
        self.transient(parent)
        self.grab_set()
        self.result = None

        pad = {"padx": 8, "pady": 4}
        ttk.Label(self, text="Name:").pack(anchor=tk.W, **pad)
        self.name_var = tk.StringVar(value=existing.get("name", ""))
        ttk.Entry(self, textvariable=self.name_var).pack(fill=tk.X, **pad)

        ttk.Label(self, text="Title:").pack(anchor=tk.W, **pad)
        self.title_var = tk.StringVar(value=existing.get("title", ""))
        ttk.Entry(self, textvariable=self.title_var).pack(fill=tk.X, **pad)

        ttk.Label(self, text="Prompt:").pack(anchor=tk.W, **pad)
        self.prompt_text = tk.Text(self, height=12, wrap=tk.WORD)
        self.prompt_text.pack(fill=tk.BOTH, expand=True, **pad)
        if existing.get("prompt"):
            self.prompt_text.insert("1.0", existing["prompt"])

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, **pad, pady=(4, 8))
        ttk.Button(btn_frame, text="Save", command=self._ok).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=4)

    def _ok(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Missing Name", "Please enter a step name.", parent=self)
            return
        self.result = {
            "name": name,
            "title": self.title_var.get().strip(),
            "prompt": self.prompt_text.get("1.0", tk.END).strip(),
            "description": "",
        }
        self.destroy()
