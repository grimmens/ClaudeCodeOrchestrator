import tkinter as tk
from tkinter import ttk, filedialog

from ..config import ALL_TOOLS, Config, save_config


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent: tk.Tk, config: Config, on_saved=None):
        super().__init__(parent)
        self.title("Settings")
        self.geometry("540x460")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.config = config
        self.on_saved = on_saved

        self._build_ui()
        self._load_values()

    def _build_ui(self):
        pad = {"padx": 10, "pady": 3}
        row = 0

        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Max Budget
        ttk.Label(frame, text="Max Budget per step ($):").grid(row=row, column=0, sticky=tk.W, **pad)
        budget_inner = ttk.Frame(frame)
        budget_inner.grid(row=row, column=1, sticky=tk.W, **pad)
        self.budget_var = tk.DoubleVar()
        ttk.Spinbox(budget_inner, textvariable=self.budget_var, from_=0.0, to=100.0, increment=0.5, width=10).pack(side=tk.LEFT)
        ttk.Label(budget_inner, text="(0 = unlimited)", foreground="gray").pack(side=tk.LEFT, padx=(6, 0))
        row += 1

        # Max Turns
        ttk.Label(frame, text="Max Turns per step:").grid(row=row, column=0, sticky=tk.W, **pad)
        self.turns_var = tk.IntVar()
        ttk.Spinbox(frame, textvariable=self.turns_var, from_=1, to=500, increment=1, width=10).grid(
            row=row, column=1, sticky=tk.W, **pad)
        row += 1

        # Claude CLI Path
        ttk.Label(frame, text="Claude CLI Path:").grid(row=row, column=0, sticky=tk.W, **pad)
        cli_frame = ttk.Frame(frame)
        cli_frame.grid(row=row, column=1, sticky=tk.W, **pad)
        self.cli_var = tk.StringVar()
        ttk.Entry(cli_frame, textvariable=self.cli_var, width=30).pack(side=tk.LEFT)
        ttk.Button(cli_frame, text="Browse", command=self._browse_cli).pack(side=tk.LEFT, padx=(5, 0))
        row += 1

        # Permission Mode
        ttk.Separator(frame, orient=tk.HORIZONTAL).grid(row=row, column=0, columnspan=2, sticky=tk.EW, pady=8)
        row += 1

        ttk.Label(frame, text="Permission Mode:", font=("", 9, "bold")).grid(
            row=row, column=0, columnspan=2, sticky=tk.W, **pad)
        row += 1

        self.perm_mode_var = tk.StringVar(value="override")

        ttk.Radiobutton(frame, text="Override — grant all permissions automatically (recommended)",
                        variable=self.perm_mode_var, value="override",
                        command=self._on_perm_mode_changed).grid(
            row=row, column=0, columnspan=2, sticky=tk.W, **pad)
        row += 1

        ttk.Radiobutton(frame, text="Selective — only allow checked tools below",
                        variable=self.perm_mode_var, value="selective",
                        command=self._on_perm_mode_changed).grid(
            row=row, column=0, columnspan=2, sticky=tk.W, **pad)
        row += 1

        # Tool checkboxes
        self.tools_frame = ttk.LabelFrame(frame, text="Allowed Tools")
        self.tools_frame.grid(row=row, column=0, columnspan=2, sticky=tk.EW, **pad)
        row += 1

        self.tool_vars: dict[str, tk.BooleanVar] = {}
        for i, tool in enumerate(ALL_TOOLS):
            var = tk.BooleanVar(value=True)
            self.tool_vars[tool] = var
            ttk.Checkbutton(self.tools_frame, text=tool, variable=var).grid(
                row=i // 3, column=i % 3, sticky=tk.W, padx=8, pady=2)

        ttk.Separator(frame, orient=tk.HORIZONTAL).grid(row=row, column=0, columnspan=2, sticky=tk.EW, pady=8)
        row += 1

        # Include Context
        self.context_var = tk.BooleanVar()
        ttk.Checkbutton(frame, text="Include Previous Step Context", variable=self.context_var).grid(
            row=row, column=0, columnspan=2, sticky=tk.W, **pad)
        row += 1

        # Include History Context
        self.history_context_var = tk.BooleanVar()
        ttk.Checkbutton(frame, text="Include Plan History in Agent Context",
                        variable=self.history_context_var).grid(
            row=row, column=0, columnspan=2, sticky=tk.W, **pad)
        row += 1

        # Database Path
        ttk.Label(frame, text="Database Path:").grid(row=row, column=0, sticky=tk.W, **pad)
        self.db_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.db_var, width=40, state="readonly").grid(
            row=row, column=1, sticky=tk.W, **pad)
        row += 1

        # Buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=(5, 10))
        ttk.Button(btn_frame, text="Save", command=self._save).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=5)

    def _load_values(self):
        self.budget_var.set(self.config.max_budget_usd)
        self.turns_var.set(self.config.max_turns)
        self.cli_var.set(self.config.claude_cli_path)
        self.context_var.set(self.config.include_context)
        self.history_context_var.set(self.config.include_history_context)
        self.db_var.set(self.config.db_path)
        self.perm_mode_var.set(self.config.permission_mode)

        # Set tool checkboxes from allowed_tools string
        enabled_tools = set(self.config.allowed_tools.split())
        for tool, var in self.tool_vars.items():
            var.set(tool in enabled_tools)

        self._on_perm_mode_changed()

    def _on_perm_mode_changed(self):
        state = tk.NORMAL if self.perm_mode_var.get() == "selective" else tk.DISABLED
        for child in self.tools_frame.winfo_children():
            child.configure(state=state)

    def _browse_cli(self):
        path = filedialog.askopenfilename(title="Select Claude CLI Executable")
        if path:
            self.cli_var.set(path)

    def _save(self):
        self.config.max_budget_usd = self.budget_var.get()
        self.config.max_turns = self.turns_var.get()
        self.config.claude_cli_path = self.cli_var.get()
        self.config.include_context = self.context_var.get()
        self.config.include_history_context = self.history_context_var.get()
        self.config.permission_mode = self.perm_mode_var.get()

        # Build allowed_tools string from checkboxes
        selected = [tool for tool, var in self.tool_vars.items() if var.get()]
        self.config.allowed_tools = " ".join(selected)

        save_config(self.config)
        if self.on_saved:
            self.on_saved()
        self.destroy()
