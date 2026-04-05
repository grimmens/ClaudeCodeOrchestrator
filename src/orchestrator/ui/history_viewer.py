import json
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from typing import Optional

from ..database import Database
from ..models import PlanHistory


class HistoryViewer(tk.Toplevel):
    """Toplevel window for browsing and managing plan history snapshots."""

    def __init__(self, parent, db: Database, plan_id: str,
                 auto_select_step_name: str | None = None):
        super().__init__(parent)
        self.db = db
        self.plan_id = plan_id
        self._auto_select_step_name = auto_select_step_name

        plan = db.get_plan(plan_id)
        self._plan_name = plan.name if plan else "Unknown"
        self.title(f"Plan History - {self._plan_name}")
        self.geometry("1100x700")
        self.minsize(900, 550)

        self._snapshots: list[PlanHistory] = []
        self._current_steps: list[dict] = []
        # Map snapshot_id -> plan_name for lineage grouping
        self._snapshot_plan_names: dict[str, str] = {}

        self._build_ui()
        self._load_snapshots()

    def _build_ui(self):
        # Toolbar
        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, padx=5, pady=5)

        ttk.Button(toolbar, text="Create Snapshot Now",
                   command=self._create_snapshot).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Delete Snapshot",
                   command=self._delete_snapshot).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Refresh",
                   command=self._load_snapshots).pack(side=tk.LEFT, padx=2)

        self._lineage_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(toolbar, text="View Full Lineage",
                        variable=self._lineage_var,
                        command=self._load_snapshots).pack(side=tk.LEFT, padx=(10, 2))

        # Top: snapshot list
        snap_frame = ttk.LabelFrame(self, text="Snapshots")
        snap_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 2))

        columns = ("Snapshot Name", "Date", "Summary")
        self.snap_tree = ttk.Treeview(snap_frame, columns=columns,
                                      show="tree headings", selectmode="browse")
        self.snap_tree.heading("#0", text="Plan")
        self.snap_tree.column("#0", width=150)
        for col in columns:
            self.snap_tree.heading(col, text=col)
        self.snap_tree.column("Snapshot Name", width=200)
        self.snap_tree.column("Date", width=180)
        self.snap_tree.column("Summary", width=400)

        snap_scroll = ttk.Scrollbar(snap_frame, orient=tk.VERTICAL,
                                    command=self.snap_tree.yview)
        self.snap_tree.configure(yscrollcommand=snap_scroll.set)
        snap_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.snap_tree.pack(fill=tk.BOTH, expand=True)

        self.snap_tree.bind("<<TreeviewSelect>>", self._on_snapshot_selected)

        # Bottom: paned window with step list (left) and result text (right)
        detail_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        detail_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        # Left: step list
        step_frame = ttk.LabelFrame(detail_pane, text="Steps in Snapshot")
        detail_pane.add(step_frame, weight=1)

        step_cols = ("#", "Name", "Title", "Status")
        self.step_tree = ttk.Treeview(step_frame, columns=step_cols,
                                      show="headings", selectmode="browse")
        for col in step_cols:
            self.step_tree.heading(col, text=col)
        self.step_tree.column("#", width=40, stretch=False)
        self.step_tree.column("Name", width=120)
        self.step_tree.column("Title", width=200)
        self.step_tree.column("Status", width=80, stretch=False)

        step_scroll = ttk.Scrollbar(step_frame, orient=tk.VERTICAL,
                                    command=self.step_tree.yview)
        self.step_tree.configure(yscrollcommand=step_scroll.set)
        step_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.step_tree.pack(fill=tk.BOTH, expand=True)

        # Status color tags
        self.step_tree.tag_configure("pending", background="")
        self.step_tree.tag_configure("queued", background="#E3F2FD")
        self.step_tree.tag_configure("running", background="#FFF9C4")
        self.step_tree.tag_configure("succeeded", background="#E8F5E9")
        self.step_tree.tag_configure("failed", background="#FFEBEE")
        self.step_tree.tag_configure("skipped", background="#F5F5F5")

        self.step_tree.bind("<<TreeviewSelect>>", self._on_step_selected)

        # Right: result text
        result_frame = ttk.LabelFrame(detail_pane, text="Step Result")
        detail_pane.add(result_frame, weight=2)

        self.result_text = tk.Text(result_frame, wrap=tk.WORD, state=tk.DISABLED)
        result_scroll = ttk.Scrollbar(result_frame, orient=tk.VERTICAL,
                                      command=self.result_text.yview)
        self.result_text.configure(yscrollcommand=result_scroll.set)
        result_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.result_text.pack(fill=tk.BOTH, expand=True)

    def _load_snapshots(self):
        for item in self.snap_tree.get_children():
            self.snap_tree.delete(item)
        self._snapshots.clear()
        self._snapshot_plan_names.clear()

        if self._lineage_var.get():
            all_history = self.db.get_full_lineage_history(self.plan_id)
        else:
            all_history = self.db.get_history_for_plan(self.plan_id)

        self._snapshots = all_history

        if self._lineage_var.get():
            # Group by plan_id
            groups: dict[str, list[PlanHistory]] = {}
            plan_names: dict[str, str] = {}
            for h in all_history:
                if h.plan_id not in groups:
                    groups[h.plan_id] = []
                    plan = self.db.get_plan(h.plan_id)
                    plan_names[h.plan_id] = plan.name if plan else "(deleted)"
                groups[h.plan_id].append(h)

            for pid, snapshots in groups.items():
                group_id = f"group_{pid}"
                pname = plan_names[pid]
                self.snap_tree.insert("", tk.END, iid=group_id, text=pname,
                                      open=True)
                for h in snapshots:
                    self._snapshot_plan_names[h.id] = pname
                    date_display = h.snapshot_at[:19].replace("T", " ")
                    self.snap_tree.insert(group_id, tk.END, iid=h.id,
                                          text="",
                                          values=(h.snapshot_name, date_display,
                                                  h.summary or ""))
        else:
            for h in all_history:
                self._snapshot_plan_names[h.id] = self._plan_name
                date_display = h.snapshot_at[:19].replace("T", " ")
                self.snap_tree.insert("", tk.END, iid=h.id,
                                      text=self._plan_name,
                                      values=(h.snapshot_name, date_display,
                                              h.summary or ""))

        # Auto-select the most recent snapshot if requested
        if self._auto_select_step_name and self._snapshots:
            last = self._snapshots[-1]
            self.snap_tree.selection_set(last.id)
            self.snap_tree.see(last.id)
            self.snap_tree.event_generate("<<TreeviewSelect>>")
            # Will auto-select the step after steps load (handled in _on_snapshot_selected)

    def _on_snapshot_selected(self, event=None):
        sel = self.snap_tree.selection()
        if not sel:
            return
        snap_id = sel[0]
        # Skip group nodes
        if snap_id.startswith("group_"):
            return

        snapshot = next((s for s in self._snapshots if s.id == snap_id), None)
        if not snapshot:
            return

        # Load steps from snapshot
        for item in self.step_tree.get_children():
            self.step_tree.delete(item)
        self._current_steps.clear()
        self._set_result_text("")

        try:
            steps_data = json.loads(snapshot.steps_json)
        except (json.JSONDecodeError, TypeError):
            steps_data = []

        self._current_steps = steps_data
        for i, step in enumerate(steps_data):
            status = step.get("status", "pending")
            self.step_tree.insert("", tk.END, iid=f"snap_step_{i}",
                                  values=(
                                      step.get("queue_position", i) + 1,
                                      step.get("name", ""),
                                      step.get("title", ""),
                                      status,
                                  ), tags=(status,))

        # Auto-select step by name if requested
        if self._auto_select_step_name:
            for i, step in enumerate(steps_data):
                if step.get("name", "") == self._auto_select_step_name:
                    item_id = f"snap_step_{i}"
                    self.step_tree.selection_set(item_id)
                    self.step_tree.see(item_id)
                    self.step_tree.event_generate("<<TreeviewSelect>>")
                    break
            # Clear after first use so subsequent clicks don't re-trigger
            self._auto_select_step_name = None

    def _on_step_selected(self, event=None):
        sel = self.step_tree.selection()
        if not sel:
            return
        item_id = sel[0]
        # Extract index from "snap_step_N"
        try:
            idx = int(item_id.split("_")[-1])
        except (ValueError, IndexError):
            return
        if 0 <= idx < len(self._current_steps):
            result = self._current_steps[idx].get("result") or "(no result)"
            self._set_result_text(result)

    def _create_snapshot(self):
        name = simpledialog.askstring("Create Snapshot",
                                      "Snapshot name:", parent=self)
        if not name:
            return
        summary = simpledialog.askstring("Create Snapshot",
                                         "Summary (optional):", parent=self)
        self.db.create_history_snapshot(self.plan_id, name, summary or None)
        self._load_snapshots()

    def _delete_snapshot(self):
        sel = self.snap_tree.selection()
        if not sel:
            messagebox.showwarning("Delete Snapshot", "No snapshot selected.",
                                   parent=self)
            return
        snap_id = sel[0]
        if snap_id.startswith("group_"):
            messagebox.showwarning("Delete Snapshot",
                                   "Select a specific snapshot, not a group.",
                                   parent=self)
            return
        snapshot = next((s for s in self._snapshots if s.id == snap_id), None)
        if not snapshot:
            return
        if not messagebox.askyesno("Delete Snapshot",
                                   f"Delete snapshot '{snapshot.snapshot_name}'?",
                                   parent=self):
            return
        self.db.delete_history_snapshot(snapshot.id)
        self._load_snapshots()
        # Clear detail panels
        for item in self.step_tree.get_children():
            self.step_tree.delete(item)
        self._current_steps.clear()
        self._set_result_text("")

    def _set_result_text(self, text: str):
        self.result_text.config(state=tk.NORMAL)
        self.result_text.delete("1.0", tk.END)
        self.result_text.insert("1.0", text)
        self.result_text.config(state=tk.DISABLED)
