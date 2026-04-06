import json
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from typing import Optional

from ..database import Database
from ..models import PlanHistory
from .snapshot_diff_dialog import SnapshotDiffDialog


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
        self._timeline_mode = False

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
        ttk.Button(toolbar, text="Compare",
                   command=self._compare_snapshots).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Export History",
                   command=self._export_history).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Refresh",
                   command=self._load_snapshots).pack(side=tk.LEFT, padx=2)

        self._lineage_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(toolbar, text="View Full Lineage",
                        variable=self._lineage_var,
                        command=self._load_snapshots).pack(side=tk.LEFT, padx=(10, 2))

        self._timeline_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(toolbar, text="Timeline View",
                        variable=self._timeline_var,
                        command=self._toggle_timeline).pack(side=tk.LEFT, padx=(10, 2))

        # Container that holds either the list view or timeline view
        self._view_container = ttk.Frame(self)
        self._view_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 2))

        # List view: snapshot treeview
        self._list_frame = ttk.LabelFrame(self._view_container, text="Snapshots")

        columns = ("Snapshot Name", "Date", "Summary")
        self.snap_tree = ttk.Treeview(self._list_frame, columns=columns,
                                      show="tree headings", selectmode="extended")
        self.snap_tree.heading("#0", text="Plan")
        self.snap_tree.column("#0", width=150)
        for col in columns:
            self.snap_tree.heading(col, text=col)
        self.snap_tree.column("Snapshot Name", width=200)
        self.snap_tree.column("Date", width=180)
        self.snap_tree.column("Summary", width=400)

        snap_scroll = ttk.Scrollbar(self._list_frame, orient=tk.VERTICAL,
                                    command=self.snap_tree.yview)
        self.snap_tree.configure(yscrollcommand=snap_scroll.set)
        snap_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.snap_tree.pack(fill=tk.BOTH, expand=True)

        self.snap_tree.bind("<<TreeviewSelect>>", self._on_snapshot_selected)

        self._list_frame.pack(fill=tk.BOTH, expand=True)

        # Timeline view: canvas-based horizontal timeline
        self._timeline_frame = ttk.LabelFrame(self._view_container, text="Timeline")
        self._timeline_canvas = tk.Canvas(self._timeline_frame, height=130,
                                          bg="white")
        self._timeline_h_scroll = ttk.Scrollbar(self._timeline_frame,
                                                orient=tk.HORIZONTAL,
                                                command=self._timeline_canvas.xview)
        self._timeline_canvas.configure(xscrollcommand=self._timeline_h_scroll.set)
        self._timeline_h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self._timeline_canvas.pack(fill=tk.BOTH, expand=True)
        self._timeline_canvas.bind("<Button-1>", self._on_timeline_click)
        # Timeline frame is not packed initially — toggled via checkbox

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

    def _toggle_timeline(self):
        self._timeline_mode = self._timeline_var.get()
        if self._timeline_mode:
            self._list_frame.pack_forget()
            self._timeline_frame.pack(fill=tk.BOTH, expand=True)
            self._draw_timeline()
        else:
            self._timeline_frame.pack_forget()
            self._list_frame.pack(fill=tk.BOTH, expand=True)

    def _draw_timeline(self):
        canvas = self._timeline_canvas
        canvas.delete("all")
        self._timeline_hit_regions: list[tuple[int, int, str]] = []

        snapshots = [s for s in self._snapshots]
        if not snapshots:
            canvas.create_text(200, 60, text="No snapshots", fill="gray")
            return

        spacing = 180
        margin = 60
        total_width = margin * 2 + spacing * max(len(snapshots) - 1, 0)
        canvas.configure(scrollregion=(0, 0, max(total_width, 600), 130))

        y_line = 40
        canvas.create_line(margin, y_line, total_width - margin + spacing // 2,
                           y_line, fill="#BDBDBD", width=2)

        for i, snap in enumerate(snapshots):
            x = margin + i * spacing

            # Point on the line
            canvas.create_oval(x - 7, y_line - 7, x + 7, y_line + 7,
                               fill="#1976D2", outline="#0D47A1", width=2,
                               tags=f"point_{snap.id}")

            # Snapshot name above
            date_str = snap.snapshot_at[:10]
            canvas.create_text(x, y_line - 18, text=snap.snapshot_name,
                               font=("TkDefaultFont", 8, "bold"), anchor=tk.S)
            canvas.create_text(x, y_line - 8, text=date_str,
                               font=("TkDefaultFont", 7), fill="gray",
                               anchor=tk.S)

            # Mini summary below
            try:
                steps = json.loads(snap.steps_json)
            except (json.JSONDecodeError, TypeError):
                steps = []
            succeeded = sum(1 for s in steps if s.get("status") == "succeeded")
            failed = sum(1 for s in steps if s.get("status") == "failed")
            summary_text = f"{succeeded} ok, {failed} fail"
            canvas.create_text(x, y_line + 20, text=summary_text,
                               font=("TkDefaultFont", 7), anchor=tk.N)

            self._timeline_hit_regions.append((x - 30, x + 30, snap.id))

    def _on_timeline_click(self, event):
        x = self._timeline_canvas.canvasx(event.x)
        for x_min, x_max, snap_id in getattr(self, '_timeline_hit_regions', []):
            if x_min <= x <= x_max:
                # Select the snapshot in the tree and trigger display
                if self.snap_tree.exists(snap_id):
                    self.snap_tree.selection_set(snap_id)
                    self.snap_tree.see(snap_id)
                # Also directly show the snapshot details
                snapshot = next((s for s in self._snapshots if s.id == snap_id), None)
                if snapshot:
                    self._show_snapshot_steps(snapshot)
                break

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

        # Redraw timeline if in timeline mode
        if self._timeline_mode:
            self._draw_timeline()

    def _on_snapshot_selected(self, event=None):
        sel = self.snap_tree.selection()
        if not sel:
            return
        # Use the first non-group selection for display
        snap_id = sel[0]
        # Skip group nodes
        if snap_id.startswith("group_"):
            return

        snapshot = next((s for s in self._snapshots if s.id == snap_id), None)
        if not snapshot:
            return

        self._show_snapshot_steps(snapshot)

    def _show_snapshot_steps(self, snapshot: PlanHistory):
        """Populate the step tree and result area from a snapshot."""
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

    def _compare_snapshots(self):
        """Open a side-by-side diff of two selected snapshots."""
        sel = self.snap_tree.selection()
        # Filter out group nodes
        snap_ids = [s for s in sel if not s.startswith("group_")]

        if len(snap_ids) != 2:
            messagebox.showinfo(
                "Compare Snapshots",
                "Select exactly two snapshots to compare.\n"
                "Hold Ctrl and click to select multiple.",
                parent=self)
            return

        snap_a = next((s for s in self._snapshots if s.id == snap_ids[0]), None)
        snap_b = next((s for s in self._snapshots if s.id == snap_ids[1]), None)

        if not snap_a or not snap_b:
            messagebox.showerror("Compare Snapshots",
                                 "Could not find selected snapshots.",
                                 parent=self)
            return

        SnapshotDiffDialog(self, snap_a, snap_b)

    def _export_history(self):
        """Export all snapshots for this plan (or full lineage) as JSON."""
        if self._lineage_var.get():
            snapshots = self.db.get_full_lineage_history(self.plan_id)
        else:
            snapshots = self.db.get_history_for_plan(self.plan_id)

        if not snapshots:
            messagebox.showinfo("Export History", "No snapshots to export.",
                                parent=self)
            return

        export_data = {
            "plan_id": self.plan_id,
            "plan_name": self._plan_name,
            "include_lineage": self._lineage_var.get(),
            "exported_at": __import__("datetime").datetime.now().isoformat(),
            "snapshots": [],
        }

        for snap in snapshots:
            try:
                steps = json.loads(snap.steps_json)
            except (json.JSONDecodeError, TypeError):
                steps = []
            plan_name = self._snapshot_plan_names.get(snap.id, self._plan_name)
            export_data["snapshots"].append({
                "id": snap.id,
                "plan_id": snap.plan_id,
                "plan_name": plan_name,
                "snapshot_name": snap.snapshot_name,
                "snapshot_at": snap.snapshot_at,
                "summary": snap.summary,
                "steps": steps,
            })

        file_path = filedialog.asksaveasfilename(
            parent=self,
            title="Export History",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile=f"{self._plan_name}_history.json",
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            messagebox.showinfo("Export History",
                                f"Exported {len(snapshots)} snapshot(s) to:\n{file_path}",
                                parent=self)
        except OSError as e:
            messagebox.showerror("Export History",
                                 f"Failed to export: {e}",
                                 parent=self)

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
