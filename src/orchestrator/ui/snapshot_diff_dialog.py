import json
import tkinter as tk
from tkinter import ttk

from ..models import PlanHistory


class SnapshotDiffDialog(tk.Toplevel):
    """Side-by-side comparison of two plan history snapshots."""

    def __init__(self, parent, snapshot_a: PlanHistory, snapshot_b: PlanHistory):
        super().__init__(parent)
        self.title(f"Compare: {snapshot_a.snapshot_name} vs {snapshot_b.snapshot_name}")
        self.geometry("1400x750")
        self.minsize(1000, 550)

        self._snap_a = snapshot_a
        self._snap_b = snapshot_b
        self._steps_a = self._parse_steps(snapshot_a.steps_json)
        self._steps_b = self._parse_steps(snapshot_b.steps_json)
        self._diff = self._compute_diff()

        self._build_ui()

    @staticmethod
    def _parse_steps(steps_json: str) -> list[dict]:
        try:
            return json.loads(steps_json)
        except (json.JSONDecodeError, TypeError):
            return []

    def _compute_diff(self) -> dict:
        """Compare steps between snapshot A and B by step name."""
        a_by_name = {s.get("name", ""): s for s in self._steps_a}
        b_by_name = {s.get("name", ""): s for s in self._steps_b}

        added = []
        removed = []
        status_changed = []
        result_changed = []

        for name, step_b in b_by_name.items():
            if name not in a_by_name:
                added.append(step_b)
            else:
                step_a = a_by_name[name]
                a_status = step_a.get("status", "pending")
                b_status = step_b.get("status", "pending")
                if a_status != b_status:
                    status_changed.append({
                        "name": name,
                        "title": step_b.get("title", ""),
                        "old_status": a_status,
                        "new_status": b_status,
                    })
                a_result = step_a.get("result") or ""
                b_result = step_b.get("result") or ""
                if a_result != b_result and name not in [s.get("name") for s in added]:
                    result_changed.append({
                        "name": name,
                        "title": step_b.get("title", ""),
                    })

        for name, step_a in a_by_name.items():
            if name not in b_by_name:
                removed.append(step_a)

        return {
            "added": added,
            "removed": removed,
            "status_changed": status_changed,
            "result_changed": result_changed,
        }

    def _build_ui(self):
        # Main horizontal pane: left | summary | right
        main_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left: Snapshot A
        left_frame = self._build_snapshot_panel(
            main_pane, self._snap_a, self._steps_a, "a")
        main_pane.add(left_frame, weight=2)

        # Center: diff summary
        center_frame = self._build_summary_panel(main_pane)
        main_pane.add(center_frame, weight=1)

        # Right: Snapshot B
        right_frame = self._build_snapshot_panel(
            main_pane, self._snap_b, self._steps_b, "b")
        main_pane.add(right_frame, weight=2)

    def _build_snapshot_panel(self, parent, snapshot: PlanHistory,
                              steps: list[dict], side: str) -> ttk.LabelFrame:
        date_str = snapshot.snapshot_at[:19].replace("T", " ")
        frame = ttk.LabelFrame(parent, text=f"{snapshot.snapshot_name} ({date_str})")

        cols = ("#", "Name", "Title", "Status")
        tree = ttk.Treeview(frame, columns=cols, show="headings",
                            selectmode="browse", height=12)
        for col in cols:
            tree.heading(col, text=col)
        tree.column("#", width=35, stretch=False)
        tree.column("Name", width=110)
        tree.column("Title", width=180)
        tree.column("Status", width=75, stretch=False)

        # Color tags
        tree.tag_configure("pending", background="")
        tree.tag_configure("queued", background="#E3F2FD")
        tree.tag_configure("running", background="#FFF9C4")
        tree.tag_configure("succeeded", background="#E8F5E9")
        tree.tag_configure("failed", background="#FFEBEE")
        tree.tag_configure("skipped", background="#F5F5F5")
        tree.tag_configure("reference", background="#F3E5F5")
        # Diff highlight tags
        tree.tag_configure("diff_added", background="#C8E6C9")
        tree.tag_configure("diff_removed", background="#FFCDD2")
        tree.tag_configure("diff_changed", background="#FFF9C4")

        other_names = {s.get("name", "") for s in
                       (self._steps_b if side == "a" else self._steps_a)}

        for i, step in enumerate(steps):
            status = step.get("status", "pending")
            name = step.get("name", "")
            tags = [status]
            if side == "b" and name not in {s.get("name", "") for s in self._steps_a}:
                tags = ["diff_added"]
            elif side == "a" and name not in {s.get("name", "") for s in self._steps_b}:
                tags = ["diff_removed"]
            elif any(c["name"] == name for c in self._diff["status_changed"]):
                tags = ["diff_changed"]

            tree.insert("", tk.END, iid=f"{side}_step_{i}",
                        values=(step.get("queue_position", i) + 1,
                                name,
                                step.get("title", ""),
                                status),
                        tags=tuple(tags))

        scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        tree.pack(fill=tk.BOTH, expand=True)

        # Result text below
        result_text = tk.Text(frame, wrap=tk.WORD, state=tk.DISABLED, height=10)
        result_scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL,
                                      command=result_text.yview)
        result_text.configure(yscrollcommand=result_scroll.set)
        result_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        result_text.pack(fill=tk.BOTH, expand=True, pady=(3, 0))

        # Store references
        if side == "a":
            self._tree_a = tree
            self._result_a = result_text
            self._steps_a_list = steps
        else:
            self._tree_b = tree
            self._result_b = result_text
            self._steps_b_list = steps

        tree.bind("<<TreeviewSelect>>",
                  lambda e, s=side: self._on_step_selected(s))
        return frame

    def _on_step_selected(self, side: str):
        tree = self._tree_a if side == "a" else self._tree_b
        result_text = self._result_a if side == "a" else self._result_b
        steps = self._steps_a_list if side == "a" else self._steps_b_list

        sel = tree.selection()
        if not sel:
            return
        try:
            idx = int(sel[0].split("_")[-1])
        except (ValueError, IndexError):
            return
        if 0 <= idx < len(steps):
            text = steps[idx].get("result") or "(no result)"
            result_text.config(state=tk.NORMAL)
            result_text.delete("1.0", tk.END)
            result_text.insert("1.0", text)
            result_text.config(state=tk.DISABLED)

    def _build_summary_panel(self, parent) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Differences")

        text = tk.Text(frame, wrap=tk.WORD, state=tk.DISABLED, width=35)
        text.tag_configure("header", font=("TkDefaultFont", 10, "bold"))
        text.tag_configure("added", foreground="#2E7D32")
        text.tag_configure("removed", foreground="#C62828")
        text.tag_configure("changed", foreground="#F57F17")

        scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        text.pack(fill=tk.BOTH, expand=True)

        text.config(state=tk.NORMAL)

        diff = self._diff
        if diff["added"]:
            text.insert(tk.END, "Steps Added in B:\n", "header")
            for s in diff["added"]:
                text.insert(tk.END, f"  + {s.get('name', '')} ({s.get('status', '')})\n", "added")
            text.insert(tk.END, "\n")

        if diff["removed"]:
            text.insert(tk.END, "Steps Removed from A:\n", "header")
            for s in diff["removed"]:
                text.insert(tk.END, f"  - {s.get('name', '')} ({s.get('status', '')})\n", "removed")
            text.insert(tk.END, "\n")

        if diff["status_changed"]:
            text.insert(tk.END, "Status Changed:\n", "header")
            for c in diff["status_changed"]:
                text.insert(tk.END,
                            f"  ~ {c['name']}: {c['old_status']} \u2192 {c['new_status']}\n",
                            "changed")
            text.insert(tk.END, "\n")

        if diff["result_changed"]:
            text.insert(tk.END, "Results Differ:\n", "header")
            for c in diff["result_changed"]:
                text.insert(tk.END, f"  ~ {c['name']}\n", "changed")
            text.insert(tk.END, "\n")

        if not any(diff.values()):
            text.insert(tk.END, "No differences found.\n")

        # Summary counts
        text.insert(tk.END, "\n")
        text.insert(tk.END, f"Snapshot A: {len(self._steps_a)} steps\n")
        text.insert(tk.END, f"Snapshot B: {len(self._steps_b)} steps\n")

        text.config(state=tk.DISABLED)
        return frame
