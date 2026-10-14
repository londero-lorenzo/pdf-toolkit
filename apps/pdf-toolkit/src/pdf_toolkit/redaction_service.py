"""Glue between the configuration, the pdf-redaction library and the user interfaces."""

from __future__ import annotations

import csv
from collections.abc import Callable
from pathlib import Path

from pdf_redaction.engines.base import Engine, load_engines
from pdf_redaction.guards import GuardError, ensure_not_within
from pdf_redaction.names import NameRedactor
from pdf_redaction.pipeline import RunReport, plan_names, run_session, verify_session
from pdf_redaction.publish import PublishReport, publish
from pdf_redaction.rules.context import RedactionContext
from pdf_redaction.session import SESSION_FILE, Session
from pdf_redaction.verify import FileVerdict
from pdf_toolkit.config import AppConfig

PREVIEW_FILE = "preview_names.csv"


def protected(cfg: AppConfig) -> list[Path]:
    r = cfg.redaction
    return list(r.protected_locations) + ([r.output_root] if r.output_root else [])


def load_context(cfg: AppConfig, source: Path | None) -> RedactionContext:
    r = cfg.redaction
    return RedactionContext.load(
        source,
        global_term_files=r.global_term_files,
        global_alias_files=r.global_alias_files,
        default_packs=r.pattern_packs,
    )


def engines(cfg: AppConfig) -> dict[str, Engine]:
    return load_engines(cfg.redaction.engine_settings, cfg.redaction.engines)


def workspace_for(cfg: AppConfig, alias: str) -> Path:
    if not cfg.redaction.workspace_root:
        raise GuardError("redaction.workspace_root is not set in the configuration")
    return cfg.redaction.workspace_root / alias


def create_session(cfg: AppConfig, source: Path, alias: str, workspace: Path | None = None) -> Session:
    # the alias becomes a public folder name (<output_root>/<alias>): it must not leak anything itself
    if NameRedactor(load_context(cfg, source)).findings(alias):
        raise GuardError("alias matches a redaction rule (term, alias, PII or long code): choose a neutral one")
    return Session.create(source, workspace or workspace_for(cfg, alias), alias, protected(cfg))


def open_session(cfg: AppConfig, ref: str | Path) -> Session:
    """``ref`` is a workspace path or an alias under ``workspace_root``."""
    path = Path(ref)
    if not (path / SESSION_FILE).exists() and cfg.redaction.workspace_root:
        path = cfg.redaction.workspace_root / str(ref)
    session = Session.open(path)
    ensure_not_within(session.workspace, protected(cfg), "workspace")
    return session


def list_sessions(cfg: AppConfig) -> list[str]:
    root = cfg.redaction.workspace_root
    if not root or not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if (p / SESSION_FILE).exists())


def preview_names(session: Session, ctx: RedactionContext) -> tuple[int, int, Path]:
    """Write original -> redacted names to a private CSV in the workspace; return (files, renamed, csv)."""
    plan = plan_names(session, ctx)
    out = session.workspace / PREVIEW_FILE
    with open(out, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(["original", "redacted"])
        writer.writerows(plan)
    return len(plan), sum(1 for o, r in plan if o != r), out


def run(
    cfg: AppConfig, session: Session, *, force: bool = False, progress: Callable[[int, int], None] | None = None
) -> RunReport:
    ctx = load_context(cfg, session.source)
    session.sync_originals()
    return run_session(session, ctx, engines(cfg), workers=cfg.redaction.workers, force=force, progress=progress)


def verify(cfg: AppConfig, session: Session) -> list[FileVerdict]:
    return verify_session(session, load_context(cfg, session.source))


def publish_session(cfg: AppConfig, session: Session, output_root: Path | None = None) -> PublishReport:
    target = output_root or cfg.redaction.output_root
    if not target:
        raise GuardError("no output folder: set redaction.output_root or pass --output")
    return publish(session, load_context(cfg, session.source), target)
