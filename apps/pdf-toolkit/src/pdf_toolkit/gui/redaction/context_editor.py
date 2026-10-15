"""Editor for a source folder's redaction context (``<source>/.redaction/``)."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from pdf_redaction.rules.context import (
    ALIASES_FILENAME,
    SETTINGS_FILENAME,
    TERMS_FILENAME,
    FolderSettings,
    context_dir,
)
from pdf_redaction.rules.patterns import available_packs
from pdf_redaction.rules.terms import (
    parse_aliases_text,
    read_aliases_text,
    read_terms_text,
    write_aliases,
    write_terms_text,
)
from pdf_toolkit import redaction_service as svc
from pdf_toolkit.config import AppConfig


class ContextEditor(tk.Toplevel):
    def __init__(self, master, cfg: AppConfig, source: Path, on_saved=None):
        super().__init__(master)
        self.cfg, self.source, self.on_saved = cfg, Path(source), on_saved
        self.title("Folder redaction context")
        self.geometry("720x560")
        self.transient(master)
        cdir = context_dir(self.source)

        ctx = svc.load_context(cfg, None)
        ttk.Label(
            self,
            text=f"Global rules from the configuration: {len(ctx.terms)} terms, {len(ctx.aliases)} aliases "
            "(not editable here). The rules below apply to this folder only.",
            wraplength=680,
        ).pack(anchor="w", padx=10, pady=(10, 4))

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=4)

        terms_frame = ttk.Frame(nb, padding=6)
        ttk.Label(
            terms_frame,
            text="One term per line: names, codes, addresses, dates... "
            "Lines starting with # are comments; blank lines are allowed.",
        ).pack(anchor="w")
        self.terms = tk.Text(terms_frame, height=15, undo=True)
        self.terms.pack(fill="both", expand=True)
        self.terms.insert("1.0", read_terms_text(cdir / TERMS_FILENAME))
        nb.add(terms_frame, text="Terms")

        alias_frame = ttk.Frame(nb, padding=6)
        ttk.Label(
            alias_frame,
            text="One per line: real value ; alias (the alias replaces the value). "
            "Lines starting with # are comments; blank lines are allowed.",
        ).pack(anchor="w")
        self.aliases = tk.Text(alias_frame, height=15, undo=True)
        self.aliases.pack(fill="both", expand=True)
        self.aliases.insert("1.0", read_aliases_text(cdir / ALIASES_FILENAME))
        nb.add(alias_frame, text="Aliases")

        settings = FolderSettings.load(cdir / SETTINGS_FILENAME)
        opt_frame = ttk.Frame(nb, padding=6)
        self.use_default_packs = tk.BooleanVar(value=settings.pattern_packs is None)
        ttk.Checkbutton(
            opt_frame,
            text=f"Use the default pattern packs ({', '.join(cfg.redaction.pattern_packs)})",
            variable=self.use_default_packs,
        ).pack(anchor="w")
        self.packs = {}
        for pack in available_packs():
            var = tk.BooleanVar(value=pack in (settings.pattern_packs or cfg.redaction.pattern_packs))
            ttk.Checkbutton(opt_frame, text=f"pack '{pack}'", variable=var).pack(anchor="w", padx=20)
            self.packs[pack] = var
        ttk.Label(opt_frame, text="CSV columns to drop (comma separated, by header):").pack(anchor="w", pady=(10, 0))
        self.drop = ttk.Entry(opt_frame, width=60)
        self.drop.insert(0, ", ".join(settings.drop_columns))
        self.drop.pack(anchor="w")
        nb.add(opt_frame, text="Options")

        buttons = ttk.Frame(self, padding=10)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Save", command=self.save).pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=6)

    def save(self) -> None:
        cdir = context_dir(self.source)
        try:
            aliases = parse_aliases_text(self.aliases.get("1.0", "end"))
        except ValueError as err:
            messagebox.showerror("Aliases", str(err), parent=self)
            return
        packs = None if self.use_default_packs.get() else tuple(p for p, v in self.packs.items() if v.get())
        drop = tuple(c.strip() for c in self.drop.get().split(",") if c.strip())
        write_terms_text(cdir / TERMS_FILENAME, self.terms.get("1.0", "end"))
        write_aliases(cdir / ALIASES_FILENAME, aliases)
        FolderSettings(pattern_packs=packs, drop_columns=drop).save(cdir / SETTINGS_FILENAME)
        if self.on_saved:
            self.on_saved()
        self.destroy()
