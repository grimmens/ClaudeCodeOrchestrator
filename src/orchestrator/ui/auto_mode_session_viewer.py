import tkinter as tk
from tkinter import ttk, messagebox

from ..database import Database


class AutoModeSessionViewer:
    def __init__(self, parent: tk.Misc, db: Database):
        self._db = db
        self._sessions: list = []

        self.top = tk.Toplevel(parent)
        self.top.title("Auto-mode Sessions")
        self.top.geometry("860x520")
        self.top.resizable(True, True)
        self.top.transient(parent)

        self._build()
        self._load_sessions()

    def _build(self) -> None:
        pane = ttk.PanedWindow(self.top, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        left = ttk.Frame(pane)
        pane.add(left, weight=2)

        right = ttk.Frame(pane)
        pane.add(right, weight=1)

        # Session list (left)
        ttk.Label(left, text="Sessions", font=("Segoe UI", 10, "bold")).pack(
            anchor=tk.W, padx=5, pady=(5, 2)
        )

        sess_frame = ttk.Frame(left)
        sess_frame.pack(fill=tk.BOTH, expand=True, padx=5)

        cols = ("Directive", "Status", "Batches", "Steps", "Started")
        self._sess_tree = ttk.Treeview(
            sess_frame, columns=cols, show="headings", selectmode="browse"
        )
        self._sess_tree.heading("Directive", text="Directive")
        self._sess_tree.heading("Status", text="Status")
        self._sess_tree.heading("Batches", text="Batches")
        self._sess_tree.heading("Steps", text="Steps")
        self._sess_tree.heading("Started", text="Started")
        self._sess_tree.column("Directive", width=220)
        self._sess_tree.column("Status", width=80, stretch=False)
        self._sess_tree.column("Batches", width=55, stretch=False)
        self._sess_tree.column("Steps", width=45, stretch=False)
        self._sess_tree.column("Started", width=135, stretch=False)

        sess_scroll = ttk.Scrollbar(sess_frame, orient=tk.VERTICAL, command=self._sess_tree.yview)
        self._sess_tree.configure(yscrollcommand=sess_scroll.set)
        sess_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._sess_tree.pack(fill=tk.BOTH, expand=True)
        self._sess_tree.bind("<<TreeviewSelect>>", self._on_session_selected)

        self._sess_tree.tag_configure("running", foreground="#2196F3")
        self._sess_tree.tag_configure("stopped", foreground="#4CAF50")
        self._sess_tree.tag_configure("error", foreground="#F44336")

        ttk.Button(left, text="Delete Session (keep plans)", command=self._delete_session).pack(
            padx=5, pady=5, anchor=tk.W
        )

        # Plans sub-list (right)
        ttk.Label(right, text="Plans in session", font=("Segoe UI", 10, "bold")).pack(
            anchor=tk.W, padx=5, pady=(5, 2)
        )

        plans_frame = ttk.Frame(right)
        plans_frame.pack(fill=tk.BOTH, expand=True, padx=5)

        plan_cols = ("Plan", "Steps", "Done", "Created")
        self._plans_tree = ttk.Treeview(
            plans_frame, columns=plan_cols, show="headings", selectmode="browse"
        )
        for col in plan_cols:
            self._plans_tree.heading(col, text=col)
        self._plans_tree.column("Plan", width=200)
        self._plans_tree.column("Steps", width=45, stretch=False)
        self._plans_tree.column("Done", width=45, stretch=False)
        self._plans_tree.column("Created", width=130, stretch=False)

        plan_scroll = ttk.Scrollbar(
            plans_frame, orient=tk.VERTICAL, command=self._plans_tree.yview
        )
        self._plans_tree.configure(yscrollcommand=plan_scroll.set)
        plan_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._plans_tree.pack(fill=tk.BOTH, expand=True)

    def _load_sessions(self) -> None:
        self._sessions = self._db.get_recent_auto_mode_sessions(limit=100)
        for item in self._sess_tree.get_children():
            self._sess_tree.delete(item)
        for s in self._sessions:
            directive_short = (
                (s.directive[:48] + "…") if len(s.directive) > 50 else s.directive
            )
            batches_done = max(0, s.current_batch - 1)
            started = s.created_at[:16].replace("T", " ")
            tag = s.status if s.status in ("running", "stopped", "error") else ""
            self._sess_tree.insert("", tk.END, iid=s.id, values=(
                directive_short, s.status, batches_done, s.total_steps_executed, started,
            ), tags=(tag,))

    def _on_session_selected(self, event=None) -> None:
        sel = self._sess_tree.selection()
        if not sel:
            return
        self._load_plans_for_session(sel[0])

    def _load_plans_for_session(self, session_id: str) -> None:
        for item in self._plans_tree.get_children():
            self._plans_tree.delete(item)
        all_plans = self._db.get_plans()
        session_plans = [p for p in all_plans if p.auto_mode_session_id == session_id]
        for p in sorted(session_plans, key=lambda x: x.created_at):
            steps = self._db.get_steps_for_plan(p.id)
            done = sum(1 for s in steps if s.status.value == "succeeded")
            created = p.created_at[:16].replace("T", " ")
            self._plans_tree.insert("", tk.END, values=(p.name, len(steps), done, created))

    def _delete_session(self) -> None:
        sel = self._sess_tree.selection()
        if not sel:
            messagebox.showwarning("Delete Session", "No session selected.", parent=self.top)
            return
        if not messagebox.askyesno(
            "Delete Session",
            "Delete this session record?\nAssociated plans will NOT be deleted.",
            parent=self.top,
        ):
            return
        self._db.delete_auto_mode_session(sel[0])
        self._load_sessions()
        for item in self._plans_tree.get_children():
            self._plans_tree.delete(item)
