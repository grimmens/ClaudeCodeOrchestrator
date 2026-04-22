import json
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime

from .config import load_config
from .database import Database
from .models import Plan, PlanStep, StepStatus
from .config import save_config
from .services.orchestrator import Orchestrator
from .services.json_parser import extract_json_steps
from .ui.import_preview_dialog import ImportPreviewDialog
from .ui.new_plan_dialog import NewPlanDialog
from .ui.settings_dialog import SettingsDialog
from .ui.history_viewer import HistoryViewer
from .ui.log_viewer import LogViewer
from .ui.step_editor_dialog import StepEditorDialog
from .ui.extend_plan_dialog import ExtendPlanDialog
from .ui.derive_plan_dialog import DerivePlanDialog
from .ui.template_dialog import SaveAsTemplateDialog, CreateFromTemplateDialog
from .services.auto_mode_orchestrator import AutoModeOrchestrator, AutoModeCallbacks
from .ui.auto_mode_dialog import AutoModeDialog
from .ui.auto_mode_session_viewer import AutoModeSessionViewer


class OrchestratorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("ClaudeCode Orchestrator")
        self.root.geometry("1280x800")
        self.root.minsize(1024, 768)

        self.db = Database()
        self.config = load_config()
        self.orchestrator = Orchestrator(self.db, self.config)
        self.current_plan: Plan | None = None
        self.steps: list[PlanStep] = []

        # Per-plan execution state: plan_id -> {cancel_event, ui_queue, output_lines, start_time}
        self._plan_executions: dict[str, dict] = {}
        self._polling = False
        self._elapsed_timer_id: str | None = None

        self._auto_mode_orchestrator: AutoModeOrchestrator | None = None
        self._auto_mode_session = None
        self._auto_mode_ui_queue: queue.Queue = queue.Queue()
        self._auto_mode_status: str = ""
        self._auto_mode_current_batch: int = 1
        self._auto_mode_current_step: int = 0
        self._auto_mode_total_steps: int = 0

        self._build_menu()
        self._build_toolbar()
        self._build_ui()
        self._bind_shortcuts()
        self._load_plans()
        self._setup_drag_and_drop()
        self._check_interrupted_sessions()

    # ── Menu Bar ─────────────────────────────────────────────────

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New Plan", command=self._new_plan)
        file_menu.add_command(label="New Plan from Existing...", command=self._derive_plan)
        file_menu.add_command(label="Import Plan", command=self._import_json)
        file_menu.add_command(label="Export Plan", command=self._export_json)
        file_menu.add_separator()
        file_menu.add_command(label="Save Plan as Template", command=self._save_as_template)
        file_menu.add_command(label="New Plan from Template", command=self._new_from_template)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        # Edit menu
        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Settings", command=self._open_settings)
        edit_menu.add_separator()
        edit_menu.add_command(label="Extend Plan", command=self._extend_plan)
        edit_menu.add_command(label="Create Snapshot", command=self._create_snapshot_from_menu)
        menubar.add_cascade(label="Edit", menu=edit_menu)

        # Auto-mode menu
        self._auto_mode_menu = tk.Menu(menubar, tearoff=0)
        self._auto_mode_menu.add_command(label="Start Auto-mode...", command=self._start_auto_mode)
        self._auto_mode_menu.add_command(
            label="Stop Auto-mode", command=self._stop_auto_mode, state=tk.DISABLED
        )
        self._auto_mode_menu.add_separator()
        self._auto_mode_menu.add_command(
            label="View Sessions...", command=self._view_auto_mode_sessions
        )
        menubar.add_cascade(label="Auto-mode", menu=self._auto_mode_menu)

        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self._show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

    # ── Drag and Drop ────────────────────────────────────────────

    def _setup_drag_and_drop(self):
        try:
            from tkinterdnd2 import DND_FILES
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self._on_drop)
        except (ImportError, Exception):
            pass  # tkinterdnd2 not available, skip drag-and-drop

    def _on_drop(self, event):
        file_path = event.data.strip()
        # tkinterdnd2 may wrap paths in braces on Windows
        if file_path.startswith("{") and file_path.endswith("}"):
            file_path = file_path[1:-1]
        if file_path.lower().endswith(".json"):
            self._import_json(file_path)

    # ── Toolbar ──────────────────────────────────────────────────

    def _build_toolbar(self):
        toolbar = ttk.Frame(self.root)
        toolbar.pack(fill=tk.X, side=tk.TOP)

        buttons = [
            ("\U0001F4C4 New", self._new_plan),
            ("\U0001F504 Extend", self._extend_plan),
            ("\u25B6 Run", self._run_queue),
            ("\u23F9 Stop", self._stop_queue),
            ("\U0001F4DC History", self._view_history),
            ("\u2699 Settings", self._open_settings),
        ]
        for text, cmd in buttons:
            ttk.Button(toolbar, text=text, command=cmd).pack(side=tk.LEFT, padx=2, pady=2)

    # ── Keyboard Shortcuts ───────────────────────────────────────

    def _bind_shortcuts(self):
        self.root.bind("<Control-n>", lambda e: self._new_plan())
        self.root.bind("<Control-e>", lambda e: self._extend_plan())
        self.root.bind("<Control-r>", lambda e: self._run_queue())
        self.root.bind("<Escape>", lambda e: self._stop_queue())
        self.root.bind("<Control-h>", lambda e: self._view_history())
        self.root.bind("<Delete>", lambda e: self._delete_step())
        self.root.bind("<Control-Up>", lambda e: self._move_step_up())
        self.root.bind("<Control-Down>", lambda e: self._move_step_down())
        self.root.bind("<F5>", lambda e: self._refresh_all())
        self.root.bind("<Control-A>", lambda e: self._start_auto_mode())

    def _refresh_all(self):
        self._load_plans()
        self._refresh_steps()

    # ── Menu Actions ─────────────────────────────────────────────

    def _open_settings(self):
        def _on_saved():
            self.include_context_var.set(self.config.include_context)
            self.orchestrator.config = self.config
        SettingsDialog(self.root, self.config, on_saved=_on_saved)

    def _export_json(self):
        if not self.current_plan:
            messagebox.showwarning("Export Plan", "No plan selected.")
            return
        import json
        path = filedialog.asksaveasfilename(
            title="Export Plan as JSON",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        steps = self.db.get_steps_for_plan(self.current_plan.id)
        data = {
            "name": self.current_plan.name,
            "project_root": self.current_plan.project_root,
            "steps": [
                {
                    "name": s.name,
                    "title": s.title,
                    "prompt": s.prompt,
                    "description": s.description,
                    "queue_position": s.queue_position,
                }
                for s in steps
            ],
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        messagebox.showinfo("Export Plan", f"Plan exported to {path}")

    def _show_about(self):
        messagebox.showinfo(
            "About ClaudeCode Orchestrator",
            "ClaudeCode Orchestrator v0.1\n\n"
            "A tool for orchestrating multi-step Claude Code tasks\n"
            "with plan management, step queuing, and build verification.",
        )

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

        # Progress bar (hidden by default)
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(self.root, variable=self.progress_var,
                                            maximum=100, mode="determinate")

        # Status bar
        self.status_var = tk.StringVar(value="No plan selected")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    def _build_left_pane(self, parent: ttk.Frame):
        ttk.Label(parent, text="Plans", font=("Segoe UI", 12, "bold")).pack(padx=5, pady=(5, 2), anchor=tk.W)

        # Plan search/filter
        search_frame = ttk.Frame(parent)
        search_frame.pack(fill=tk.X, padx=5, pady=(0, 2))
        ttk.Label(search_frame, text="\U0001F50D").pack(side=tk.LEFT)
        self.plan_search_var = tk.StringVar()
        plan_search_entry = ttk.Entry(search_frame, textvariable=self.plan_search_var)
        plan_search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        self.plan_search_var.trace_add("write", lambda *_: self._filter_plan_list())

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
        ttk.Button(btn_frame, text="View Logs", command=self._view_logs).pack(fill=tk.X, pady=1)
        ttk.Button(btn_frame, text="History", command=self._view_history).pack(fill=tk.X, pady=1)
        ttk.Button(btn_frame, text="Extend Plan", command=self._extend_plan).pack(fill=tk.X, pady=1)

        # Right-click context menu on plan listbox
        self._plan_context_menu = tk.Menu(self.plan_listbox, tearoff=0)
        self._plan_context_menu.add_command(label="Extend Plan", command=self._extend_plan)
        self._plan_context_menu.add_command(label="New Plan from Existing...", command=self._derive_plan)
        self._plan_context_menu.add_command(label="View History", command=self._view_history)
        self._plan_context_menu.add_command(label="View Logs", command=self._view_logs)
        self._plan_context_menu.add_command(label="Save as Template", command=self._save_as_template)
        self._plan_context_menu.add_separator()
        self._plan_context_menu.add_command(label="Delete Plan", command=self._delete_plan)
        self.plan_listbox.bind("<Button-3>", self._on_plan_right_click)

    def _build_step_queue(self, parent: ttk.Frame):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(2, weight=1)

        # Button bar
        btn_bar = ttk.Frame(parent)
        btn_bar.grid(row=0, column=0, sticky="ew", padx=5, pady=2)
        for text, cmd in [
            ("Add Step", self._add_step),
            ("Edit Step", self._edit_step),
            ("Delete Step", self._delete_step),
            ("Move Up", self._move_step_up),
            ("Move Down", self._move_step_down),
        ]:
            ttk.Button(btn_bar, text=text, command=cmd).pack(side=tk.LEFT, padx=2)

        self.run_btn = ttk.Button(btn_bar, text="Run Queue", command=self._run_queue)
        self.run_btn.pack(side=tk.LEFT, padx=2)
        self.stop_btn = ttk.Button(btn_bar, text="Stop", command=self._stop_queue, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=2)

        self.include_context_var = tk.BooleanVar(value=self.config.include_context)
        ttk.Checkbutton(btn_bar, text="Include context from previous steps",
                        variable=self.include_context_var).pack(side=tk.LEFT, padx=(10, 2))

        # Toolbar: filter, search, refresh
        toolbar = ttk.Frame(parent)
        toolbar.grid(row=1, column=0, sticky="ew", padx=5, pady=(2, 0))

        ttk.Label(toolbar, text="Filter:").pack(side=tk.LEFT, padx=(0, 2))
        self.filter_var = tk.StringVar(value="All")
        filter_combo = ttk.Combobox(toolbar, textvariable=self.filter_var, width=10,
                                    values=["All", "Pending", "Running", "Succeeded", "Failed", "Skipped", "Reference"],
                                    state="readonly")
        filter_combo.pack(side=tk.LEFT, padx=2)
        filter_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_step_filter())

        ttk.Label(toolbar, text="Search:").pack(side=tk.LEFT, padx=(10, 2))
        self.step_search_var = tk.StringVar()
        search_entry = ttk.Entry(toolbar, textvariable=self.step_search_var, width=20)
        search_entry.pack(side=tk.LEFT, padx=2)
        self.step_search_var.trace_add("write", lambda *_: self._apply_step_filter())

        ttk.Button(toolbar, text="Refresh", command=self._refresh_steps).pack(side=tk.LEFT, padx=(10, 2))

        # Treeview for steps
        tree_frame = ttk.Frame(parent)
        tree_frame.grid(row=2, column=0, sticky="nsew", padx=5, pady=2)

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
        self.step_tree.bind("<Button-3>", self._on_step_right_click)

        # Status color tags
        self.step_tree.tag_configure("pending", background="")
        self.step_tree.tag_configure("queued", background="#E3F2FD")
        self.step_tree.tag_configure("running", background="#FFF9C4")
        self.step_tree.tag_configure("succeeded", background="#E8F5E9")
        self.step_tree.tag_configure("failed", background="#FFEBEE")
        self.step_tree.tag_configure("skipped", background="#F5F5F5")
        self.step_tree.tag_configure("reference", background="#F3E5F5")
        self.step_tree.tag_configure("section_divider", background="#B0BEC5", foreground="#455A64")

        # Right-click context menu
        self._step_context_menu = tk.Menu(self.step_tree, tearoff=0)
        self._step_context_menu.add_command(label="Edit Step", command=self._edit_step)
        self._step_context_menu.add_command(label="Run This Step Only", command=self._run_single_step)
        self._step_context_menu.add_separator()
        self._step_context_menu.add_command(label="Skip Step", command=self._skip_step)
        self._step_context_menu.add_command(label="Reset Step", command=self._reset_step)
        self._step_context_menu.add_separator()
        self._step_context_menu.add_command(label="View Full Result", command=self._view_full_result)
        self._step_context_menu.add_command(label="Copy Result to Clipboard", command=self._copy_result_to_clipboard)
        self._step_context_menu.add_separator()
        self._step_context_menu.add_command(label="View Run History", command=self._view_step_run_history)
        self._step_context_menu.add_command(label="View History for This Step", command=self._view_history_for_step)

        # Auto-mode status panel (hidden by default, shown when a session is active)
        self._auto_mode_panel = tk.Frame(parent, relief=tk.GROOVE, bd=1)
        self._build_auto_mode_panel_contents()
        self._auto_mode_panel.grid(row=3, column=0, sticky="ew", padx=5, pady=(0, 2))
        self._auto_mode_panel.grid_remove()

    def _build_output_viewer(self, parent: ttk.Frame):
        ttk.Label(parent, text="Step Result", font=("Segoe UI", 10, "bold")).pack(padx=5, pady=(5, 2), anchor=tk.W)
        text_frame = ttk.Frame(parent)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 2))

        self.output_text = tk.Text(text_frame, wrap=tk.WORD, state=tk.DISABLED)
        out_scroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.output_text.yview)
        self.output_text.configure(yscrollcommand=out_scroll.set)
        out_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.output_text.pack(fill=tk.BOTH, expand=True)
        self.output_text.tag_configure("search_highlight", background="#FFFF00")
        self.output_text.bind("<Double-1>", self._open_fullscreen_result)

        # Search bar for result text
        search_bar = ttk.Frame(parent)
        search_bar.pack(fill=tk.X, padx=5, pady=(0, 5))
        ttk.Label(search_bar, text="Find:").pack(side=tk.LEFT, padx=(0, 2))
        self.result_search_var = tk.StringVar()
        result_search_entry = ttk.Entry(search_bar, textvariable=self.result_search_var, width=30)
        result_search_entry.pack(side=tk.LEFT, padx=2)
        ttk.Button(search_bar, text="Find", command=self._find_in_result).pack(side=tk.LEFT, padx=2)
        ttk.Button(search_bar, text="Clear", command=self._clear_result_search).pack(side=tk.LEFT, padx=2)
        result_search_entry.bind("<Return>", lambda e: self._find_in_result())

    # ── Data Loading ─────────────────────────────────────────────

    def _load_plans(self):
        # Remember current selection
        cur_sel = self.plan_listbox.curselection()
        cur_idx = cur_sel[0] if cur_sel else None

        self._plans = self.db.get_plans()
        # Cache step data per plan for display
        self._plan_step_cache: dict[str, list[PlanStep]] = {}
        for p in self._plans:
            self._plan_step_cache[p.id] = self.db.get_steps_for_plan(p.id)

        self._filter_plan_list(restore_idx=cur_idx)

    def _filter_plan_list(self, *_args, restore_idx: int | None = None):
        """Rebuild the plan listbox applying the search filter."""
        cur_sel = self.plan_listbox.curselection()
        cur_idx = restore_idx if restore_idx is not None else (cur_sel[0] if cur_sel else None)

        search = self.plan_search_var.get().strip().lower() if hasattr(self, "plan_search_var") else ""
        self.plan_listbox.delete(0, tk.END)
        self._filtered_plan_indices: list[int] = []

        parent_name_map = {p.id: p.name for p in self._plans}

        for i, p in enumerate(self._plans):
            if search and search not in p.name.lower():
                continue
            self._filtered_plan_indices.append(i)
            steps = self._plan_step_cache.get(p.id, [])
            badge, fg_color = self._get_plan_status_badge(p, steps)
            succeeded = sum(1 for s in steps if s.status == StepStatus.SUCCEEDED)
            total = len(steps)
            running = " [RUNNING]" if p.id in self._plan_executions else ""
            if p.parent_plan_id:
                parent_name = parent_name_map.get(p.parent_plan_id, "?")
                lineage_suffix = f"  \u21b3 derived from {parent_name[:25]}"
            else:
                lineage_suffix = ""
            am_prefix = "⚡ " if p.auto_mode_session_id else ""
            label = f"{am_prefix}{badge} {p.name}  ({succeeded}/{total}){running}{lineage_suffix}"
            self.plan_listbox.insert(tk.END, label)
            list_idx = self.plan_listbox.size() - 1
            self.plan_listbox.itemconfig(list_idx, fg=fg_color)

        if cur_idx is not None:
            # Find the filtered position for the original index
            if cur_idx in self._filtered_plan_indices:
                new_pos = self._filtered_plan_indices.index(cur_idx)
                self.plan_listbox.selection_set(new_pos)

    def _get_plan_status_badge(self, plan: Plan, steps: list[PlanStep]) -> tuple[str, str]:
        """Return (badge_char, color) for the plan's overall status."""
        if plan.id in self._plan_executions:
            return ("\u25CF", "#FFC107")  # yellow dot - in progress
        if not steps:
            return ("\u25CB", "#9E9E9E")  # gray circle - no steps
        statuses = {s.status for s in steps}
        if all(s.status == StepStatus.SUCCEEDED for s in steps):
            return ("\u25CF", "#4CAF50")  # green dot - all succeeded
        if StepStatus.FAILED in statuses:
            return ("\u25CF", "#F44336")  # red dot - has failures
        if StepStatus.RUNNING in statuses:
            return ("\u25CF", "#FFC107")  # yellow dot - running
        if any(s.status == StepStatus.SUCCEEDED for s in steps):
            return ("\u25D4", "#2196F3")  # half circle - partially done
        return ("\u25CB", "#9E9E9E")  # gray circle - not started

    def _load_steps(self):
        for item in self.step_tree.get_children():
            self.step_tree.delete(item)
        self.steps = []
        if not self.current_plan:
            return
        self.steps = self.db.get_steps_for_plan(self.current_plan.id)

        # Determine if we need a divider between completed and pending sections
        completed_statuses = {StepStatus.SUCCEEDED, StepStatus.FAILED, StepStatus.SKIPPED,
                              StepStatus.REFERENCE}
        pending_statuses = {StepStatus.PENDING, StepStatus.QUEUED}
        has_completed = any(s.status in completed_statuses for s in self.steps)
        has_pending = any(s.status in pending_statuses for s in self.steps)
        need_divider = has_completed and has_pending
        divider_inserted = False

        for s in self.steps:
            # Insert divider before first pending/queued step if there are completed steps above
            if need_divider and not divider_inserted and s.status in pending_statuses:
                self.step_tree.insert("", tk.END, iid="__divider__", values=(
                    "", "\u2500\u2500\u2500", "New / Pending Steps", "", "",
                ), tags=("section_divider",))
                divider_inserted = True

            prompt_preview = (s.prompt[:60] + "\u2026") if len(s.prompt) > 60 else s.prompt
            self.step_tree.insert("", tk.END, iid=s.id, values=(
                s.queue_position + 1, s.name, s.title, s.status.value, prompt_preview,
            ), tags=(s.status.value,))

    def _is_plan_running(self, plan_id: str | None = None) -> bool:
        pid = plan_id or (self.current_plan.id if self.current_plan else None)
        return pid is not None and pid in self._plan_executions

    def _sync_run_buttons(self):
        """Update Run/Stop button state based on the currently selected plan."""
        if self._is_plan_running():
            self.run_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
        else:
            self.run_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)

    def _update_status_bar(self):
        if not self.current_plan:
            self.status_var.set("No plan selected")
            return
        total = len(self.steps)
        done = sum(1 for s in self.steps if s.status == StepStatus.SUCCEEDED)
        running_count = len(self._plan_executions)

        # Cost
        runs = self.db.get_runs_for_plan(self.current_plan.id)
        total_cost = sum(r.cost_usd or 0 for r in runs)
        cost_str = f"${total_cost:.2f}" if total_cost > 0 else "$0.00"

        # Elapsed time
        elapsed_str = ""
        exec_ctx = self._plan_executions.get(self.current_plan.id)
        if exec_ctx and "start_time" in exec_ctx:
            elapsed = time.time() - exec_ctx["start_time"]
            mins, secs = divmod(int(elapsed), 60)
            elapsed_str = f"  |  Elapsed: {mins}m {secs}s"

        # Snapshot count
        snapshots = self.db.get_history_for_plan(self.current_plan.id)
        snap_str = f"  |  Snapshots: {len(snapshots)}" if snapshots else ""

        running_suffix = f"  |  {running_count} plan(s) running" if running_count else ""
        self.status_var.set(
            f"Plan: {self.current_plan.name}  |  "
            f"Steps: {done}/{total}  |  "
            f"Cost: {cost_str}{snap_str}{elapsed_str}{running_suffix}"
        )

    # ── Event Handlers ───────────────────────────────────────────

    def _on_plan_selected(self, event):
        sel = self.plan_listbox.curselection()
        if not sel:
            return
        # Map filtered listbox index back to the original plan index
        filtered_idx = sel[0]
        if hasattr(self, "_filtered_plan_indices") and filtered_idx < len(self._filtered_plan_indices):
            original_idx = self._filtered_plan_indices[filtered_idx]
        else:
            original_idx = filtered_idx
        self.current_plan = self._plans[original_idx]
        self.path_var.set(self.current_plan.project_root)
        self._load_steps()
        self._sync_run_buttons()
        # Show buffered output if this plan is running, else reset
        exec_ctx = self._plan_executions.get(self.current_plan.id)
        if exec_ctx:
            self._set_output_text("".join(exec_ctx["output_lines"]))
        else:
            self._set_output_text("No result yet")
        self._update_status_bar()

    def _on_step_selected(self, event):
        sel = self.step_tree.selection()
        if not sel:
            return
        # Always fetch the latest result from the database
        step = self.db.get_step(sel[0])
        if step:
            # Update the in-memory list as well
            for i, s in enumerate(self.steps):
                if s.id == step.id:
                    self.steps[i] = step
                    break
            self._set_output_text(step.result or "No result yet")

    # ── Plan Actions ─────────────────────────────────────────────

    def _new_plan(self):
        NewPlanDialog(self.root, self.db, on_saved=self._load_plans)

    def _delete_plan(self):
        if not self.current_plan:
            messagebox.showwarning("Delete Plan", "No plan selected.")
            return
        if self._is_plan_running():
            messagebox.showwarning("Delete Plan", "Cannot delete a running plan. Stop it first.")
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

    def _import_json(self, file_path: str | None = None):
        if not file_path:
            file_path = filedialog.askopenfilename(
                title="Import Plan from JSON",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            )
        if not file_path:
            return
        try:
            with open(file_path, "r") as f:
                raw_text = f.read()
        except OSError as e:
            messagebox.showerror("Import Error", f"Failed to read file:\n{e}")
            return

        try:
            steps_data, warnings = extract_json_steps(raw_text)
        except ValueError as e:
            messagebox.showerror("Import Error", str(e))
            return

        if warnings:
            messagebox.showinfo("Import", "Parsed with fixups:\n" + "\n".join(warnings))

        ImportPreviewDialog(self.root, self.db, steps_data, on_saved=self._load_plans)

    def _extend_plan(self):
        if not self.current_plan:
            messagebox.showwarning("Extend Plan", "No plan selected.")
            return
        if self._is_plan_running():
            messagebox.showwarning("Extend Plan", "Cannot extend a running plan. Stop it first.")
            return

        # Auto-create a history snapshot before extending
        steps = self.db.get_steps_for_plan(self.current_plan.id)
        has_results = any(s.status != StepStatus.PENDING for s in steps)
        if has_results:
            from datetime import datetime
            snap_name = f"pre-extend-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            self.db.create_history_snapshot(self.current_plan.id, snap_name,
                                           "Auto-snapshot before plan extension")

        def _on_saved():
            self._load_steps()
            self._update_status_bar()

        ExtendPlanDialog(self.root, self.db, self.current_plan.id, on_saved=_on_saved)

    def _derive_plan(self):
        plans = self.db.get_plans()
        if not plans:
            messagebox.showwarning("New Plan from Existing", "No plans available.")
            return
        selected_id = self.current_plan.id if self.current_plan else None

        def _on_saved(new_plan_id: str):
            self._load_plans()
            # Select the newly created plan
            for i, p in enumerate(self._plans):
                if p.id == new_plan_id:
                    self.plan_listbox.selection_clear(0, tk.END)
                    self.plan_listbox.selection_set(i)
                    self.plan_listbox.event_generate("<<ListboxSelect>>")
                    break

        DerivePlanDialog(self.root, self.db, plans, selected_plan_id=selected_id,
                         on_saved=_on_saved)

    def _save_as_template(self):
        if not self.current_plan:
            messagebox.showwarning("Save as Template", "No plan selected.")
            return
        steps = self.db.get_steps_for_plan(self.current_plan.id)
        has_succeeded = any(s.status == StepStatus.SUCCEEDED for s in steps)
        if not has_succeeded:
            messagebox.showwarning("Save as Template",
                                   "Plan must have at least one succeeded step to save as a template.")
            return
        SaveAsTemplateDialog(self.root, self.db, self.current_plan.id)

    def _new_from_template(self):
        def _on_saved(new_plan_id: str):
            self._load_plans()
            for i, p in enumerate(self._plans):
                if p.id == new_plan_id:
                    self.plan_listbox.selection_clear(0, tk.END)
                    self.plan_listbox.selection_set(i)
                    self.plan_listbox.event_generate("<<ListboxSelect>>")
                    break

        CreateFromTemplateDialog(self.root, self.db, on_saved=_on_saved)

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
        if not self.current_plan:
            messagebox.showwarning("Run Queue", "No plan selected.")
            return
        if not self.current_plan.project_root:
            messagebox.showwarning("Run Queue", "Set a project path first.")
            return
        if self._is_plan_running():
            messagebox.showwarning("Run Queue", "This plan is already running.")
            return
        pending = [s for s in self.steps if s.status in (StepStatus.PENDING, StepStatus.QUEUED)]
        if not pending:
            messagebox.showinfo("Run Queue", "No pending steps to run.")
            return

        plan_id = self.current_plan.id
        cancel_event = threading.Event()
        ui_q = queue.Queue()
        self._plan_executions[plan_id] = {
            "cancel_event": cancel_event,
            "ui_queue": ui_q,
            "output_lines": [],
            "start_time": time.time(),
            "total_steps": len(pending),
            "completed_steps": 0,
        }

        self._sync_run_buttons()
        self._set_output_text("")
        self._update_plan_list_labels()

        # Show progress bar
        self.progress_var.set(0)
        self.progress_bar.pack(fill=tk.X, side=tk.BOTTOM, before=self.main_pane)

        # Start elapsed time timer
        self._start_elapsed_timer()

        self.orchestrator.include_context = self.include_context_var.get()

        def _on_step_started(step, step_num, total):
            ui_q.put(("step_started", (plan_id, step, step_num, total)))

        def _on_step_completed(step):
            ui_q.put(("step_completed", (plan_id, step)))

        def _on_step_failed(step, error):
            ui_q.put(("step_failed", (plan_id, step, error)))

        def _on_output(text):
            ui_q.put(("output", (plan_id, text)))

        def _worker():
            try:
                self.orchestrator.execute_queue(
                    plan_id,
                    on_step_started=_on_step_started,
                    on_step_completed=_on_step_completed,
                    on_step_failed=_on_step_failed,
                    on_output=_on_output,
                    cancel_event=cancel_event,
                )
            finally:
                ui_q.put(("done", plan_id))

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        self._start_polling()

    def _stop_queue(self):
        if self.current_plan and self._is_plan_running():
            self._plan_executions[self.current_plan.id]["cancel_event"].set()
            self.status_var.set(f"Cancelling {self.current_plan.name}...")

    # ── UI Queue Polling (handles all running plans) ───────────

    def _start_polling(self):
        if not self._polling:
            self._polling = True
            self._poll_ui_queue()

    def _poll_ui_queue(self):
        current_plan_id = self.current_plan.id if self.current_plan else None
        finished_plans: list[str] = []

        for plan_id, ctx in list(self._plan_executions.items()):
            try:
                while True:
                    msg_type, data = ctx["ui_queue"].get_nowait()
                    is_visible = (plan_id == current_plan_id)

                    if msg_type == "output":
                        _, text = data
                        ctx["output_lines"].append(text)
                        if is_visible:
                            self._append_output(text)

                    elif msg_type == "step_started":
                        _, step, step_num, total = data
                        if is_visible:
                            self._update_step_row(step)
                            self.status_var.set(
                                f"Running step {step_num} of {total}: {step.title}"
                            )

                    elif msg_type == "step_completed":
                        _, step = data
                        ctx["completed_steps"] = ctx.get("completed_steps", 0) + 1
                        total_s = ctx.get("total_steps", 1)
                        if total_s > 0:
                            self.progress_var.set(ctx["completed_steps"] / total_s * 100)
                        if is_visible:
                            self._update_step_row(step)

                    elif msg_type == "step_failed":
                        _, step, error = data
                        ctx["completed_steps"] = ctx.get("completed_steps", 0) + 1
                        total_s = ctx.get("total_steps", 1)
                        if total_s > 0:
                            self.progress_var.set(ctx["completed_steps"] / total_s * 100)
                        if is_visible:
                            self._update_step_row(step)

                    elif msg_type == "done":
                        finished_plans.append(data)  # data is plan_id

            except queue.Empty:
                pass

        for plan_id in finished_plans:
            self._on_execution_done(plan_id)

        if self._plan_executions:
            self.root.after(100, self._poll_ui_queue)
        else:
            self._polling = False

    def _on_execution_done(self, plan_id: str):
        self._plan_executions.pop(plan_id, None)
        self._update_plan_list_labels()

        # Hide progress bar if no more running plans
        if not self._plan_executions:
            self.progress_bar.pack_forget()
            self.progress_var.set(0)
            self._stop_elapsed_timer()

        is_visible = self.current_plan and self.current_plan.id == plan_id
        steps = self.db.get_steps_for_plan(plan_id)
        succeeded = sum(1 for s in steps if s.status == StepStatus.SUCCEEDED)
        failed = sum(1 for s in steps if s.status == StepStatus.FAILED)
        total = len(steps)

        if is_visible:
            self._sync_run_buttons()
            self._load_steps()
            self._update_status_bar()
            self._show_toast(f"Plan completed: {succeeded}/{total} steps succeeded"
                             + (f", {failed} failed" if failed else ""))
        else:
            plan = self.db.get_plan(plan_id)
            plan_name = plan.name if plan else plan_id
            self._update_status_bar()
            self._show_toast(f"Background plan '{plan_name}' finished: {succeeded}/{total} succeeded")

    def _update_plan_list_labels(self):
        """Refresh the plan list labels to show/hide running indicators."""
        # Refresh step cache and rebuild filtered list
        for p in self._plans:
            self._plan_step_cache[p.id] = self.db.get_steps_for_plan(p.id)
        self._filter_plan_list()

    def _get_lineage_label(self, plan: Plan) -> str:
        """Return a lineage indicator string if the plan has a parent."""
        if not plan.parent_plan_id:
            return ""
        parent = self.db.get_plan(plan.parent_plan_id)
        if parent:
            return f"  \u2190 derived from {parent.name}"
        return ""

    def _update_step_row(self, step: PlanStep):
        """Update a single row in the Treeview to reflect the step's current status."""
        if self.step_tree.exists(step.id):
            prompt_preview = (step.prompt[:60] + "\u2026") if len(step.prompt) > 60 else step.prompt
            self.step_tree.item(step.id, values=(
                step.queue_position + 1, step.name, step.title, step.status.value, prompt_preview,
            ))
            # Color-code by status
            tag = step.status.value
            self.step_tree.item(step.id, tags=(tag,))

    def _append_output(self, text: str):
        self.output_text.config(state=tk.NORMAL)
        self.output_text.insert(tk.END, text)
        self.output_text.see(tk.END)
        self.output_text.config(state=tk.DISABLED)

    # ── Toolbar / Filter ─────────────────────────────────────────

    def _apply_step_filter(self):
        """Rebuild the Treeview showing only steps matching filter + search."""
        # Remember current selection
        sel = self.step_tree.selection()
        selected_id = sel[0] if sel else None

        for item in self.step_tree.get_children():
            self.step_tree.delete(item)
        status_filter = self.filter_var.get().lower()
        search_text = self.step_search_var.get().strip().lower()

        completed_statuses = {StepStatus.SUCCEEDED, StepStatus.FAILED, StepStatus.SKIPPED,
                              StepStatus.REFERENCE}
        pending_statuses = {StepStatus.PENDING, StepStatus.QUEUED}
        filtered = [s for s in self.steps
                    if (status_filter == "all" or s.status.value == status_filter)
                    and (not search_text or search_text in s.name.lower() or search_text in s.title.lower())]
        has_completed = any(s.status in completed_statuses for s in filtered)
        has_pending = any(s.status in pending_statuses for s in filtered)
        need_divider = has_completed and has_pending and status_filter == "all"
        divider_inserted = False

        for s in filtered:
            if need_divider and not divider_inserted and s.status in pending_statuses:
                self.step_tree.insert("", tk.END, iid="__divider__", values=(
                    "", "\u2500\u2500\u2500", "New / Pending Steps", "", "",
                ), tags=("section_divider",))
                divider_inserted = True

            prompt_preview = (s.prompt[:60] + "\u2026") if len(s.prompt) > 60 else s.prompt
            self.step_tree.insert("", tk.END, iid=s.id, values=(
                s.queue_position + 1, s.name, s.title, s.status.value, prompt_preview,
            ), tags=(s.status.value,))

        # Restore selection if it's still visible after filtering
        if selected_id and self.step_tree.exists(selected_id):
            self.step_tree.selection_set(selected_id)
            self.step_tree.focus(selected_id)

    def _refresh_steps(self):
        """Reload steps from DB, re-apply filter, restore selection, and show latest result."""
        # Remember the currently selected step
        sel = self.step_tree.selection()
        selected_id = sel[0] if sel else None

        self._load_steps()
        self._apply_step_filter()
        self._update_status_bar()

        # Restore selection and show latest result
        if selected_id and self.step_tree.exists(selected_id):
            self.step_tree.selection_set(selected_id)
            self.step_tree.focus(selected_id)
            step = next((s for s in self.steps if s.id == selected_id), None)
            if step:
                self._set_output_text(step.result or "No result yet")

    # ── Context Menu ─────────────────────────────────────────────

    def _on_step_right_click(self, event):
        row_id = self.step_tree.identify_row(event.y)
        if row_id:
            self.step_tree.selection_set(row_id)
            self._step_context_menu.tk_popup(event.x_root, event.y_root)

    def _get_selected_step(self) -> "PlanStep | None":
        sel = self.step_tree.selection()
        if not sel:
            return None
        return next((s for s in self.steps if s.id == sel[0]), None)

    def _skip_step(self):
        step = self._get_selected_step()
        if not step:
            return
        step.status = StepStatus.SKIPPED
        self.db.update_step(step)
        self._update_step_row(step)

    def _reset_step(self):
        step = self._get_selected_step()
        if not step:
            return
        step.status = StepStatus.PENDING
        step.result = None
        self.db.update_step(step)
        self._update_step_row(step)
        self._set_output_text("No result yet")

    def _view_full_result(self):
        step = self._get_selected_step()
        if not step or not step.result:
            messagebox.showinfo("View Result", "No result available for this step.")
            return
        win = tk.Toplevel(self.root)
        win.title(f"Result: {step.title}")
        win.geometry("800x600")
        text_frame = ttk.Frame(win)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        text = tk.Text(text_frame, wrap=tk.WORD)
        scroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        text.pack(fill=tk.BOTH, expand=True)
        text.insert("1.0", step.result)
        text.config(state=tk.DISABLED)

    def _copy_result_to_clipboard(self):
        step = self._get_selected_step()
        if not step or not step.result:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(step.result)

    def _run_single_step(self):
        step = self._get_selected_step()
        if not step:
            return
        if not self.current_plan or not self.current_plan.project_root:
            messagebox.showwarning("Run Step", "Set a project path first.")
            return
        if self._is_plan_running():
            messagebox.showwarning("Run Step", "This plan is already running.")
            return

        plan_id = self.current_plan.id
        cancel_event = threading.Event()
        ui_q = queue.Queue()
        self._plan_executions[plan_id] = {
            "cancel_event": cancel_event,
            "ui_queue": ui_q,
            "output_lines": [],
            "start_time": time.time(),
            "total_steps": 1,
            "completed_steps": 0,
        }

        self._sync_run_buttons()
        self._set_output_text("")
        self._update_plan_list_labels()

        # Show progress bar
        self.progress_var.set(0)
        self.progress_bar.pack(fill=tk.X, side=tk.BOTTOM, before=self.main_pane)
        self._start_elapsed_timer()

        step_id = step.id
        self.orchestrator.include_context = self.include_context_var.get()

        def _on_step_started(s, step_num, total):
            ui_q.put(("step_started", (plan_id, s, step_num, total)))

        def _on_step_completed(s):
            ui_q.put(("step_completed", (plan_id, s)))

        def _on_step_failed(s, error):
            ui_q.put(("step_failed", (plan_id, s, error)))

        def _on_output(text):
            ui_q.put(("output", (plan_id, text)))

        def _worker():
            try:
                self.orchestrator.execute_single_step(
                    step_id,
                    on_step_started=_on_step_started,
                    on_step_completed=_on_step_completed,
                    on_step_failed=_on_step_failed,
                    on_output=_on_output,
                    cancel_event=cancel_event,
                )
            finally:
                ui_q.put(("done", plan_id))

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        self._start_polling()

    # ── Result Search ────────────────────────────────────────────

    def _find_in_result(self):
        """Highlight all occurrences of the search term in the result text."""
        self.output_text.tag_remove("search_highlight", "1.0", tk.END)
        term = self.result_search_var.get().strip()
        if not term:
            return
        start = "1.0"
        first_match = None
        while True:
            pos = self.output_text.search(term, start, stopindex=tk.END, nocase=True)
            if not pos:
                break
            if first_match is None:
                first_match = pos
            end = f"{pos}+{len(term)}c"
            self.output_text.tag_add("search_highlight", pos, end)
            start = end
        if first_match:
            self.output_text.see(first_match)

    def _clear_result_search(self):
        self.result_search_var.set("")
        self.output_text.tag_remove("search_highlight", "1.0", tk.END)

    # ── Log Viewer ────────────────────────────────────────────────

    def _view_logs(self):
        if not self.current_plan:
            messagebox.showwarning("View Logs", "No plan selected.")
            return
        LogViewer(self.root, self.db, self.current_plan.id)

    def _view_step_run_history(self):
        step = self._get_selected_step()
        if not step or not self.current_plan:
            return
        LogViewer(self.root, self.db, self.current_plan.id, filter_step_id=step.id)

    # ── History ────────────────────────────────────────────────────

    def _view_history(self):
        if not self.current_plan:
            messagebox.showwarning("View History", "No plan selected.")
            return
        HistoryViewer(self.root, self.db, self.current_plan.id)

    def _view_history_for_step(self):
        step = self._get_selected_step()
        if not step or not self.current_plan:
            return
        HistoryViewer(self.root, self.db, self.current_plan.id,
                      auto_select_step_name=step.name)

    def _create_snapshot_from_menu(self):
        if not self.current_plan:
            messagebox.showwarning("Create Snapshot", "No plan selected.")
            return
        from tkinter import simpledialog
        name = simpledialog.askstring("Create Snapshot",
                                      "Snapshot name:", parent=self.root)
        if not name:
            return
        summary = simpledialog.askstring("Create Snapshot",
                                         "Summary (optional):", parent=self.root)
        self.db.create_history_snapshot(self.current_plan.id, name, summary or None)
        messagebox.showinfo("Create Snapshot", f"Snapshot '{name}' created.")

    def _on_plan_right_click(self, event):
        idx = self.plan_listbox.nearest(event.y)
        if idx >= 0:
            self.plan_listbox.selection_clear(0, tk.END)
            self.plan_listbox.selection_set(idx)
            self.plan_listbox.event_generate("<<ListboxSelect>>")
            self._plan_context_menu.tk_popup(event.x_root, event.y_root)

    # ── Toast Notifications ──────────────────────────────────────

    def _show_toast(self, message: str, duration: int = 4000):
        """Show a temporary toast notification at the bottom of the window."""
        toast = tk.Toplevel(self.root)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)

        lbl = tk.Label(toast, text=message, bg="#323232", fg="white",
                       font=("Segoe UI", 10), padx=16, pady=8)
        lbl.pack()

        # Position at bottom-center of main window
        self.root.update_idletasks()
        rx = self.root.winfo_rootx()
        ry = self.root.winfo_rooty()
        rw = self.root.winfo_width()
        rh = self.root.winfo_height()
        toast.update_idletasks()
        tw = toast.winfo_width()
        x = rx + (rw - tw) // 2
        y = ry + rh - 60
        toast.geometry(f"+{x}+{y}")

        toast.after(duration, toast.destroy)

    # ── Full-screen Result Viewer ─────────────────────────────────

    def _open_fullscreen_result(self, event=None):
        """Open the current result text in a maximized window."""
        content = self.output_text.get("1.0", tk.END).strip()
        if not content or content == "No result yet":
            return
        step = self._get_selected_step()
        title = f"Result: {step.title}" if step else "Result"
        win = tk.Toplevel(self.root)
        win.title(title)
        win.state("zoomed")
        text_frame = ttk.Frame(win)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        text = tk.Text(text_frame, wrap=tk.WORD, font=("Consolas", 10))
        scroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        text.pack(fill=tk.BOTH, expand=True)
        text.insert("1.0", content)
        text.config(state=tk.DISABLED)

    # ── Elapsed Time Timer ────────────────────────────────────────

    def _start_elapsed_timer(self):
        self._stop_elapsed_timer()
        self._tick_elapsed()

    def _stop_elapsed_timer(self):
        if self._elapsed_timer_id:
            self.root.after_cancel(self._elapsed_timer_id)
            self._elapsed_timer_id = None

    def _tick_elapsed(self):
        if self._plan_executions:
            self._update_status_bar()
            self._elapsed_timer_id = self.root.after(1000, self._tick_elapsed)
        else:
            self._elapsed_timer_id = None

    # ── Helpers ───────────────────────────────────────────────────

    def _set_output_text(self, text: str):
        self.output_text.config(state=tk.NORMAL)
        self.output_text.delete("1.0", tk.END)
        self.output_text.insert("1.0", text)
        self.output_text.config(state=tk.DISABLED)

    # ── Auto-mode Panel Contents ──────────────────────────────────

    def _build_auto_mode_panel_contents(self) -> None:
        panel = self._auto_mode_panel

        self._auto_mode_header = tk.Label(
            panel, text="⚡ Auto-mode active",
            bg="#4CAF50", fg="white", font=("Segoe UI", 9, "bold"),
            anchor=tk.W, padx=8, pady=3,
        )
        self._auto_mode_header.pack(fill=tk.X)

        log_frame = ttk.Frame(panel)
        log_frame.pack(fill=tk.BOTH, expand=True)
        self._auto_mode_log = tk.Text(
            log_frame, height=4, wrap=tk.WORD, state=tk.DISABLED,
            font=("Consolas", 8), bg="#FAFAFA",
        )
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL,
                                    command=self._auto_mode_log.yview)
        self._auto_mode_log.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._auto_mode_log.pack(fill=tk.BOTH, expand=True)

        bottom = ttk.Frame(panel)
        bottom.pack(fill=tk.X)
        self._auto_mode_countdown_var = tk.StringVar(value="")
        tk.Label(
            bottom, textvariable=self._auto_mode_countdown_var,
            fg="#D32F2F", font=("Segoe UI", 9),
        ).pack(side=tk.LEFT, padx=5, pady=2)
        self._auto_mode_stop_btn = ttk.Button(
            bottom, text="Stop", command=self._stop_auto_mode,
        )
        self._auto_mode_stop_btn.pack(side=tk.RIGHT, padx=5, pady=2)

    # ── Auto-mode Actions ─────────────────────────────────────────

    def _check_interrupted_sessions(self) -> None:
        running = [
            s for s in self.db.get_recent_auto_mode_sessions(limit=100)
            if s.status == "running"
        ]
        for s in running:
            s.status = "error"
            s.last_error = "Session interrupted by application restart"
            self.db.update_auto_mode_session(s)
        if running:
            messagebox.showwarning(
                "Auto-mode Recovery",
                f"{len(running)} auto-mode session(s) were interrupted by a restart "
                "and have been marked as 'error'.",
            )

    def _start_auto_mode(self) -> None:
        if self._auto_mode_orchestrator:
            messagebox.showwarning("Auto-mode", "An auto-mode session is already running.")
            return
        default_root = self.current_plan.project_root if self.current_plan else ""

        def _on_start(directive: str, project_root: str) -> None:
            session = self.db.create_auto_mode_session(directive, project_root)
            callbacks = AutoModeCallbacks(
                on_status_change=lambda s: self._auto_mode_ui_queue.put(("am_status", s)),
                on_batch_started=lambda b, steps: self._auto_mode_ui_queue.put(
                    ("am_batch_started", (b, len(steps)))
                ),
                on_step_started=lambda idx, title: self._auto_mode_ui_queue.put(
                    ("am_step_started", (idx, title))
                ),
                on_step_completed=lambda idx, title, exc: self._auto_mode_ui_queue.put(
                    ("am_step_completed", (idx, title, exc))
                ),
                on_step_failed=lambda idx, title, err: self._auto_mode_ui_queue.put(
                    ("am_step_failed", (idx, title, err))
                ),
                on_retry_countdown=lambda rem: self._auto_mode_ui_queue.put(
                    ("am_countdown", rem)
                ),
                on_batch_completed=lambda b, succ, fail: self._auto_mode_ui_queue.put(
                    ("am_batch_completed", (b, succ, fail))
                ),
                on_log=lambda msg: self._auto_mode_ui_queue.put(("am_log", msg)),
                on_session_ended=lambda reason: self._auto_mode_ui_queue.put(
                    ("am_ended", reason)
                ),
            )
            self._auto_mode_orchestrator = AutoModeOrchestrator(
                session, self.db, self.config, callbacks
            )
            self._auto_mode_session = session
            self._auto_mode_status = "starting"
            self._auto_mode_current_batch = 1
            self._auto_mode_current_step = 0
            self._auto_mode_total_steps = 0
            self._show_auto_mode_panel()
            self._auto_mode_menu.entryconfig(0, state=tk.DISABLED)
            self._auto_mode_menu.entryconfig(1, state=tk.NORMAL)
            self._auto_mode_orchestrator.start()
            self._start_auto_mode_polling()

        AutoModeDialog(self.root, start_callback=_on_start, default_project_root=default_root)

    def _stop_auto_mode(self) -> None:
        if self._auto_mode_orchestrator:
            self._auto_mode_orchestrator.stop()
            self._auto_mode_stop_btn.config(
                text="Stopping… (waiting for step)", state=tk.DISABLED
            )

    def _view_auto_mode_sessions(self) -> None:
        AutoModeSessionViewer(self.root, self.db)

    def _show_auto_mode_panel(self) -> None:
        self._auto_mode_panel.grid()

    def _hide_auto_mode_panel(self) -> None:
        self._auto_mode_panel.grid_remove()
        self._auto_mode_countdown_var.set("")
        self._auto_mode_stop_btn.config(text="Stop", state=tk.NORMAL)

    def _update_auto_mode_header(self) -> None:
        batch = self._auto_mode_current_batch
        step = self._auto_mode_current_step
        total = self._auto_mode_total_steps
        if self._auto_mode_status == "waiting_retry":
            bg = "#FF9800"
            text = f"⚡ Auto-mode waiting to retry - Batch {batch}"
        else:
            bg = "#4CAF50"
            text = f"⚡ Auto-mode active - Batch {batch} - Step {step}/{total}"
        self._auto_mode_header.config(text=text, bg=bg)

    def _auto_mode_log_message(self, msg: str) -> None:
        self._auto_mode_log.config(state=tk.NORMAL)
        self._auto_mode_log.insert(tk.END, msg + "\n")
        line_count = int(self._auto_mode_log.index("end-1c").split(".")[0])
        if line_count > 20:
            self._auto_mode_log.delete("1.0", f"{line_count - 20}.0")
        self._auto_mode_log.see(tk.END)
        self._auto_mode_log.config(state=tk.DISABLED)

    def _handle_auto_mode_message(self, msg_type: str, data) -> None:
        if msg_type == "am_status":
            self._auto_mode_status = data
            self._update_auto_mode_header()

        elif msg_type == "am_batch_started":
            batch_num, step_count = data
            self._auto_mode_current_batch = batch_num
            self._auto_mode_current_step = 0
            self._auto_mode_total_steps = step_count
            self._auto_mode_log_message(f"Batch {batch_num} started ({step_count} steps)")
            self._update_auto_mode_header()
            self._load_plans()

        elif msg_type == "am_step_started":
            idx, title = data
            self._auto_mode_current_step = idx + 1
            self._auto_mode_log_message(
                f"  Step {idx + 1}/{self._auto_mode_total_steps}: {title}"
            )
            self._update_auto_mode_header()

        elif msg_type == "am_step_completed":
            _idx, title, _excerpt = data
            self._auto_mode_log_message(f"  ✓ {title}")

        elif msg_type == "am_step_failed":
            _idx, title, error = data
            self._auto_mode_log_message(f"  ✗ {title}: {error[:80]}")

        elif msg_type == "am_countdown":
            remaining = data
            mins, secs = divmod(remaining, 60)
            self._auto_mode_countdown_var.set(
                f"Retrying in {mins}:{secs:02d} (usage limit reached)"
            )

        elif msg_type == "am_batch_completed":
            batch, succeeded, _failed = data
            self._auto_mode_log_message(f"Batch {batch} completed: {succeeded} succeeded")
            self._auto_mode_countdown_var.set("")
            self._load_plans()

        elif msg_type == "am_log":
            self._auto_mode_log_message(data)

        elif msg_type == "am_ended":
            session = self._auto_mode_session
            batches = max(0, session.current_batch - 1) if session else 0
            steps = session.total_steps_executed if session else 0
            self._hide_auto_mode_panel()
            self._auto_mode_orchestrator = None
            self._auto_mode_menu.entryconfig(0, state=tk.NORMAL)
            self._auto_mode_menu.entryconfig(1, state=tk.DISABLED)
            self._show_toast(
                f"Auto-mode stopped after {batches} batch(es), {steps} total steps"
            )
            self._load_plans()

    def _start_auto_mode_polling(self) -> None:
        self._poll_auto_mode_queue()

    def _poll_auto_mode_queue(self) -> None:
        try:
            while True:
                msg_type, data = self._auto_mode_ui_queue.get_nowait()
                self._handle_auto_mode_message(msg_type, data)
        except queue.Empty:
            pass
        if self._auto_mode_orchestrator is not None:
            self.root.after(200, self._poll_auto_mode_queue)


def main():
    try:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
    except (ImportError, Exception):
        root = tk.Tk()
    OrchestratorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
