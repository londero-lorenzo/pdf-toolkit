"""Redaction tab: session -> folder context -> name preview -> run -> review -> publish."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from pdf_redaction.pipeline import plan_names
from pdf_redaction.session import Session
from pdf_redaction.verify import FileVerdict, Status
from pdf_toolkit import redaction_service as svc
from pdf_toolkit.config import AppConfig
from pdf_toolkit.gui.files import open_with_default_app
from pdf_toolkit.gui.redaction.context_editor import ContextEditor
from pdf_toolkit.gui.shell import describe_error

STATUS_COLORS = {"OK": "#e6f4ea", "WARN": "#fff4d6", "FAIL": "#fde2e1", "SKIP": "#eeeeee", "ERR": "#fde2e1"}


class RedactionTab(ttk.Frame):
    def __init__(self, master, cfg: AppConfig):
        super().__init__(master, padding=8)
        self.cfg = cfg
        self.session: Session | None = None
        self._events: queue.Queue = queue.Queue()
        self._busy = False
        self._build()
        self.after(100, self._poll)
        self.refresh_sessions()

    # ----- layout -----------------------------------------------------------------------------
    def _build(self) -> None:
        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="Session:").pack(side="left")
        self.session_box = ttk.Combobox(top, width=32, state="readonly")
        self.session_box.pack(side="left", padx=4)
        self.session_box.bind("<<ComboboxSelected>>", lambda _e: self.open_session(self.session_box.get()))
        ttk.Button(top, text="New session from folder...", command=self.new_session).pack(side="left", padx=4)
        self.info = ttk.Label(top, text="No session open", foreground="#555")
        self.info.pack(side="left", padx=12)

        actions = ttk.Frame(self, padding=(0, 8))
        actions.pack(fill="x")
        self.buttons = {}
        for key, label, cmd in [
            ("context", "1. Folder context...", self.edit_context),
            ("preview", "2. Preview names", self.preview_names),
            ("run", "3. Redact + verify", self.run),
            ("verify", "Verify again", self.verify),
            ("publish", "4. Publish", self.publish),
        ]:
            b = ttk.Button(actions, text=label, command=cmd, state="disabled")
            b.pack(side="left", padx=(0, 6))
            self.buttons[key] = b
        self.progress = ttk.Progressbar(actions, length=220, mode="determinate")
        self.progress.pack(side="right")

        cols = ("status", "path", "details", "reviewed")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="extended")
        for col, width in zip(cols, (60, 420, 480, 80), strict=True):
            self.tree.heading(col, text=col.capitalize())
            self.tree.column(col, width=width, stretch=col in ("path", "details"))
        for status, color in STATUS_COLORS.items():
            self.tree.tag_configure(status, background=color)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _e: self.open_selected())

        bottom = ttk.Frame(self, padding=(0, 6))
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Open selected (visual check)", command=self.open_selected).pack(side="left")
        ttk.Button(bottom, text="Mark reviewed", command=lambda: self.mark_reviewed(True)).pack(side="left", padx=6)
        ttk.Button(bottom, text="Unmark", command=lambda: self.mark_reviewed(False)).pack(side="left")
        self.summary = ttk.Label(bottom, text="")
        self.summary.pack(side="right")

    # ----- sessions ---------------------------------------------------------------------------
    def refresh_sessions(self) -> None:
        self.session_box["values"] = svc.list_sessions(self.cfg)

    def new_session(self) -> None:
        source = filedialog.askdirectory(parent=self, title="Folder with the original documents (read only)")
        if not source:
            return
        alias = simpledialog.askstring(
            "Session alias", "Public name of this session (letters, digits, . _ -), e.g. invoices-2025:", parent=self
        )
        if not alias:
            return
        workspace = None
        if not self.cfg.redaction.workspace_root:
            chosen = filedialog.askdirectory(parent=self, title="Private workspace folder (a copy will be made here)")
            if not chosen:
                return
            workspace = Path(chosen) / alias

        def job():
            return svc.create_session(self.cfg, Path(source), alias.strip(), workspace)

        self._background(job, self._session_created, "Copying originals...")

    def _session_created(self, session: Session) -> None:
        self.refresh_sessions()
        self._set_session(session)
        if messagebox.askyesno(
            "Folder context", "Session created. Edit the folder's redaction context now?", parent=self
        ):
            self.edit_context()

    def open_session(self, ref: str) -> None:
        try:
            self._set_session(svc.open_session(self.cfg, ref))
        except Exception as exc:
            messagebox.showerror("Open session", describe_error(exc), parent=self)

    def _set_session(self, session: Session) -> None:
        self.session = session
        self.session_box.set(session.alias)
        for b in self.buttons.values():
            b.state(["!disabled"])
        self._update_info()
        self.verify()

    def _update_info(self) -> None:
        if not self.session:
            return
        ctx = svc.load_context(self.cfg, self.session.source)
        self.info.config(
            text=f"{len(self.session.manifest())} files | {len(ctx.terms)} terms, {len(ctx.aliases)} aliases, "
            f"{len(ctx.patterns)} patterns | source: {self.session.source}"
        )

    # ----- actions ----------------------------------------------------------------------------
    def edit_context(self) -> None:
        if self.session:
            ContextEditor(self, self.cfg, self.session.source, on_saved=self._update_info)

    def preview_names(self) -> None:
        if not self.session:
            return
        plan = plan_names(self.session, svc.load_context(self.cfg, self.session.source))
        win = tk.Toplevel(self)
        win.title("Name preview (shown on screen only)")
        win.geometry("1000x500")
        tree = ttk.Treeview(win, columns=("original", "redacted"), show="headings")
        for col in ("original", "redacted"):
            tree.heading(col, text=col.capitalize())
            tree.column(col, width=480)
        for original, redacted in plan:
            tree.insert("", "end", values=(original, redacted), tags=("same",) if original == redacted else ())
        tree.tag_configure("same", foreground="#777")
        tree.pack(fill="both", expand=True)
        ttk.Label(
            win,
            text="Grey rows are unchanged. A personal detail still visible on the right means a term is "
            "missing from the folder context.",
        ).pack(anchor="w", padx=6, pady=4)

    def run(self) -> None:
        if not self.session:
            return
        session = self.session

        def job():
            return svc.run(self.cfg, session, progress=lambda d, t: self._events.put(("progress", d, t)))

        self._background(job, self._show_run, "Redacting...")

    def _show_run(self, report) -> None:
        rows = []
        for item in report.items:
            if item.outcome == "unsupported":
                rows.append(("SKIP", item.redacted, "file type not supported: not processed, not published"))
            elif item.outcome == "error":
                rows.append(("ERR", item.redacted, item.error))
            else:
                rows.append(self._verdict_row(item.verdict))
        self._fill(rows)
        note = f" | rules changed: {report.context_changed} redone" if report.context_changed else ""
        self.summary.config(
            text=f"{report.count('redacted')} redacted, {report.count('unchanged')} unchanged, "
            f"remote calls {report.remote_calls}{note}"
        )

    def verify(self) -> None:
        if not self.session:
            return
        session = self.session
        self._background(lambda: svc.verify(self.cfg, session), self._show_verdicts, "Verifying...")

    def _show_verdicts(self, verdicts: list[FileVerdict]) -> None:
        self._fill([self._verdict_row(v) for v in verdicts])
        counts = {s: sum(1 for v in verdicts if v.status is s) for s in Status}
        self.summary.config(text=f"{counts[Status.OK]} OK, {counts[Status.WARN]} WARN, {counts[Status.FAIL]} FAIL")

    def publish(self) -> None:
        if not self.session:
            return
        target = self.cfg.redaction.output_root
        if not target:
            chosen = filedialog.askdirectory(parent=self, title="Output folder for the verified files")
            if not chosen:
                return
            target = Path(chosen)
        if not messagebox.askyesno(
            "Publish", f"Copy verified files to:\n{Path(target) / self.session.alias}", parent=self
        ):
            return
        session = self.session
        self._background(
            lambda: svc.publish_session(self.cfg, session, Path(target)), self._show_publish, "Publishing..."
        )

    def _show_publish(self, report) -> None:
        held = "\n".join(f"- {rel}: {reason}" for rel, reason in report.blocked[:15])
        more = f"\n... and {len(report.blocked) - 15} more" if len(report.blocked) > 15 else ""
        messagebox.showinfo(
            "Publish",
            f"{len(report.published)} published, {len(report.blocked)} held back, "
            f"{report.removed_stale} stale removed." + (f"\n\nHeld back:\n{held}{more}" if held else ""),
            parent=self,
        )

    def open_selected(self) -> None:
        if not self.session:
            return
        for iid in self.tree.selection():
            path = self.session.redacted_dir / self.tree.set(iid, "path")
            if path.exists():
                open_with_default_app(path)

    def mark_reviewed(self, value: bool) -> None:
        if not self.session:
            return
        paths = [self.tree.set(iid, "path") for iid in self.tree.selection()]
        self.session.set_reviewed(paths, value)
        for iid in self.tree.selection():
            self.tree.set(iid, "reviewed", "yes" if value else "")

    # ----- helpers ----------------------------------------------------------------------------
    def _verdict_row(self, v: FileVerdict) -> tuple[str, str, str]:
        return (v.status.value, v.rel_path, v.summary())

    def _fill(self, rows) -> None:
        reviewed = self.session.reviewed() if self.session else set()
        self.tree.delete(*self.tree.get_children())
        for status, path, details in rows:
            self.tree.insert(
                "", "end", values=(status, path, details, "yes" if path in reviewed else ""), tags=(status,)
            )

    def _background(self, job, on_done, label: str) -> None:
        if self._busy:
            return
        self._busy = True
        self.summary.config(text=label)
        self.progress.config(value=0, maximum=1)
        for b in self.buttons.values():
            b.state(["disabled"])

        def worker():
            try:
                self._events.put(("done", on_done, job()))
            except Exception as exc:  # shown in a dialog, never printed
                self._events.put(("error", exc))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                event = self._events.get_nowait()
                if event[0] == "progress":
                    self.progress.config(maximum=event[2], value=event[1])
                    continue
                self._busy = False
                if self.session:
                    for b in self.buttons.values():
                        b.state(["!disabled"])
                if event[0] == "done":
                    event[1](event[2])
                else:
                    self.summary.config(text="")
                    messagebox.showerror("pdf-toolkit", describe_error(event[1]), parent=self)
        except queue.Empty:
            pass
        self.after(100, self._poll)
