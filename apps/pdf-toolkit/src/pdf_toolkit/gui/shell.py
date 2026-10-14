"""Main window: one notebook tab per toolkit module.

The GUI never writes to stdout/stderr: Tk's default error hook (which prints a traceback) is
replaced by a dialog that shows the error type only.
"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import messagebox, ttk

from pdf_redaction.engines.base import EngineError
from pdf_redaction.guards import GuardError
from pdf_toolkit import __version__
from pdf_toolkit.config import AppConfig
from pdf_toolkit.modules import discover


def describe_error(exc: BaseException) -> str:
    if isinstance(exc, (GuardError, EngineError, FileExistsError)):
        return str(exc)
    return f"Unexpected error ({type(exc).__name__}). Use the CLI with --debug for details."


class Shell(ttk.Frame):
    def __init__(self, master: tk.Tk, cfg: AppConfig):
        super().__init__(master, padding=8)
        self.cfg = cfg
        master.title(f"pdf-toolkit {__version__}")
        master.geometry("1100x700")
        master.report_callback_exception = self._on_error
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)
        for module in discover():
            if module.create_tab:
                notebook.add(module.create_tab(notebook, cfg), text=module.title)
        if not cfg.path.exists():
            ttk.Label(
                self, text="No configuration found: run 'pdf-toolkit config init' and edit the file.", foreground="#a00"
            ).pack(anchor="w", pady=(6, 0))
        self.pack(fill="both", expand=True)

    def _on_error(self, exc_type, exc, tb) -> None:
        messagebox.showerror("pdf-toolkit", describe_error(exc), parent=self)


def run_gui(cfg: AppConfig) -> int:
    root = tk.Tk()
    Shell(root, cfg)
    root.mainloop()
    return 0


def main() -> None:
    sys.exit(run_gui(AppConfig.load()))
