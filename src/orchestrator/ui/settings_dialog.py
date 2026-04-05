import tkinter as tk
from tkinter import ttk, filedialog

from ..config import Config, save_config


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent: tk.Tk, config: Config, on_saved=None):
        super().__init__(parent)
        self.title("Settings")
        self.geometry("520x420")
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
        self.budget_var = tk.DoubleVar()
        ttk.Spinbox(frame, textvariable=self.budget_var, from_=0.1, to=100.0, increment=0.5, width=10).grid(
            row=row, column=1, sticky=tk.W, **pad)
        row += 1

        # Max Turns
        ttk.Label(frame, text="Max Turns per step:").grid(row=row, column=0, sticky=tk.W, **pad)
        self.turns_var = tk.IntVar()
        ttk.Spinbox(frame, textvariable=self.turns_var, from_=1, to=500, increment=1, width=10).grid(
            row=row, column=1, sticky=tk.W, **pad)
        row += 1

        # Build Command
        ttk.Label(frame, text="Build Command:").grid(row=row, column=0, sticky=tk.W, **pad)
        self.build_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.build_var, width=40).grid(row=row, column=1, sticky=tk.W, **pad)
        row += 1

        # Allowed Tools
        ttk.Label(frame, text="Allowed Tools:").grid(row=row, column=0, sticky=tk.W, **pad)
        self.tools_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.tools_var, width=40).grid(row=row, column=1, sticky=tk.W, **pad)
        row += 1

        # Claude CLI Path
        ttk.Label(frame, text="Claude CLI Path:").grid(row=row, column=0, sticky=tk.W, **pad)
        cli_frame = ttk.Frame(frame)
        cli_frame.grid(row=row, column=1, sticky=tk.W, **pad)
        self.cli_var = tk.StringVar()
        ttk.Entry(cli_frame, textvariable=self.cli_var, width=30).pack(side=tk.LEFT)
        ttk.Button(cli_frame, text="Browse", command=self._browse_cli).pack(side=tk.LEFT, padx=(5, 0))
        row += 1

        # Include Context
        self.context_var = tk.BooleanVar()
        ttk.Checkbutton(frame, text="Include Previous Step Context", variable=self.context_var).grid(
            row=row, column=0, columnspan=2, sticky=tk.W, **pad)
        row += 1

        # Auto-fix build
        self.autofix_var = tk.BooleanVar()
        ttk.Checkbutton(frame, text="Auto-fix on build failure", variable=self.autofix_var).grid(
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
        self.build_var.set(self.config.build_command)
        self.tools_var.set(self.config.allowed_tools)
        self.cli_var.set(self.config.claude_cli_path)
        self.context_var.set(self.config.include_context)
        self.autofix_var.set(self.config.auto_fix_build)
        self.db_var.set(self.config.db_path)

    def _browse_cli(self):
        path = filedialog.askopenfilename(title="Select Claude CLI Executable")
        if path:
            self.cli_var.set(path)

    def _save(self):
        self.config.max_budget_usd = self.budget_var.get()
        self.config.max_turns = self.turns_var.get()
        self.config.build_command = self.build_var.get()
        self.config.allowed_tools = self.tools_var.get()
        self.config.claude_cli_path = self.cli_var.get()
        self.config.include_context = self.context_var.get()
        self.config.auto_fix_build = self.autofix_var.get()
        save_config(self.config)
        if self.on_saved:
            self.on_saved()
        self.destroy()
