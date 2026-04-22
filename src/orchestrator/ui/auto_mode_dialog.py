import tkinter as tk
from tkinter import ttk, filedialog, messagebox


class AutoModeDialog:
    def __init__(self, parent: tk.Misc, start_callback, default_project_root: str = ""):
        self.top = tk.Toplevel(parent)
        self.top.title("Start Auto-mode")
        self.top.geometry("620x400")
        self.top.resizable(True, True)
        self.top.transient(parent)
        self.top.grab_set()
        self._start_callback = start_callback
        self._build(default_project_root)
        self.top.focus_set()

    def _build(self, default_project_root: str) -> None:
        ttk.Label(self.top, text="Directive:", font=("Segoe UI", 10, "bold")).pack(
            padx=10, pady=(10, 2), anchor=tk.W
        )

        text_frame = ttk.Frame(self.top)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 5))
        self._directive_text = tk.Text(text_frame, height=8, wrap=tk.WORD, font=("Segoe UI", 10))
        scroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self._directive_text.yview)
        self._directive_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._directive_text.pack(fill=tk.BOTH, expand=True)

        ttk.Label(self.top, text="Project root:", font=("Segoe UI", 10, "bold")).pack(
            padx=10, pady=(5, 2), anchor=tk.W
        )
        pr_frame = ttk.Frame(self.top)
        pr_frame.pack(fill=tk.X, padx=10, pady=(0, 5))
        self._project_root_var = tk.StringVar(value=default_project_root)
        ttk.Entry(pr_frame, textvariable=self._project_root_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        ttk.Button(pr_frame, text="Browse", command=self._browse).pack(side=tk.LEFT, padx=(5, 0))

        info_text = (
            "Auto-mode will run in a continuous loop: generate 5 steps → execute → "
            "update CLAUDE.md → repeat. A Stop button will be available during execution."
        )
        ttk.Label(
            self.top, text=info_text, wraplength=580, foreground="#555555",
            font=("Segoe UI", 9),
        ).pack(padx=10, pady=(0, 8))

        btn_frame = ttk.Frame(self.top)
        btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        ttk.Button(btn_frame, text="Cancel", command=self.top.destroy).pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="Start", command=self._on_start).pack(
            side=tk.RIGHT, padx=(0, 5)
        )

    def _browse(self) -> None:
        path = filedialog.askdirectory(title="Select Project Root", parent=self.top)
        if path:
            self._project_root_var.set(path)

    def _on_start(self) -> None:
        directive = self._directive_text.get("1.0", tk.END).strip()
        project_root = self._project_root_var.get().strip()
        if not directive:
            messagebox.showwarning("Start Auto-mode", "Directive is required.", parent=self.top)
            return
        if not project_root:
            messagebox.showwarning("Start Auto-mode", "Project root is required.", parent=self.top)
            return
        self.top.destroy()
        self._start_callback(directive, project_root)
