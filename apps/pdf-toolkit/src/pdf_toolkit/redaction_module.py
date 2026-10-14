"""The ``redact`` command family and the Redaction tab."""

from __future__ import annotations

from pathlib import Path

from pdf_redaction.audit import audit_repo
from pdf_redaction.engines.stirling import StirlingEngine
from pdf_redaction.rules.context import ALIASES_FILENAME, TERMS_FILENAME, context_dir
from pdf_redaction.rules.terms import write_aliases, write_terms
from pdf_redaction.verify import Status
from pdf_toolkit import redaction_service as svc
from pdf_toolkit.config import AppConfig
from pdf_toolkit.modules import ToolkitModule
from pdf_toolkit.safety import exit_code, totals, verdict_line


def _new(args, cfg: AppConfig) -> int:
    session = svc.create_session(cfg, Path(args.source), args.alias, Path(args.workspace) if args.workspace else None)
    print(f"session '{session.alias}' created: {len(session.manifest())} files copied to its workspace")
    return 0


def _context(args, cfg: AppConfig) -> int:
    source = Path(args.source)
    cdir = context_dir(source)
    if args.init:
        if not (cdir / TERMS_FILENAME).exists():
            write_terms(cdir / TERMS_FILENAME, [])
        if not (cdir / ALIASES_FILENAME).exists():
            write_aliases(cdir / ALIASES_FILENAME, [])
        print("folder context ready: edit .redaction/terms.txt and .redaction/aliases.csv in the source folder")
    ctx = svc.load_context(cfg, source)
    folder_terms = sum(1 for t in ctx.terms if t.label.startswith("folder"))
    print(
        f"context: {len(ctx.terms)} terms ({folder_terms} from this folder), {len(ctx.aliases)} aliases, "
        f"{len(ctx.patterns)} built-in patterns"
    )
    return 0


def _preview(args, cfg: AppConfig) -> int:
    session = svc.open_session(cfg, args.session)
    files, renamed, out = svc.preview_names(session, svc.load_context(cfg, session.source))
    print(f"{files} files, {renamed} renamed. Mapping written to {out.name} in the workspace (private).")
    return 0


def _run(args, cfg: AppConfig) -> int:
    session = svc.open_session(cfg, args.session)
    report = svc.run(cfg, session, force=args.force)
    reviewed = session.reviewed()
    verdicts = []
    for index, item in enumerate(report.items, 1):
        if item.outcome == "unsupported":
            print(f"SKIP {item.redacted}: file type not supported, not processed")
        elif item.outcome == "error":
            print(f"ERR  file#{index}: {item.error}")
        else:
            verdicts.append(item.verdict)
            print(verdict_line(item.verdict, index, item.redacted in reviewed))
    if report.context_changed:
        print(f"note: rules changed since the last run, {report.context_changed} files were redone")
    print(
        f"{report.count('redacted')} redacted, {report.count('unchanged')} unchanged, "
        f"{report.count('unsupported')} unsupported, {report.count('error')} errors; "
        f"remote engine calls: {report.remote_calls}"
    )
    print(totals(verdicts))
    return 1 if report.count("error") else exit_code(verdicts)


def _verify(args, cfg: AppConfig) -> int:
    session = svc.open_session(cfg, args.session)
    verdicts = svc.verify(cfg, session)
    reviewed = session.reviewed()
    for index, v in enumerate(verdicts, 1):
        print(verdict_line(v, index, v.rel_path in reviewed))
    print(totals(verdicts))
    return exit_code(verdicts)


def _review(args, cfg: AppConfig) -> int:
    session = svc.open_session(cfg, args.session)
    known = {v.rel_path: v for v in svc.verify(cfg, session)}
    unknown = [p for p in args.paths if p not in known]
    if unknown:
        print(f"{len(unknown)} path(s) not found among the redacted files (use the paths printed by 'run')")
        return 1
    session.set_reviewed(args.paths, not args.undo)
    print(f"{len(args.paths)} file(s) {'un' if args.undo else ''}marked as reviewed")
    return 0


def _publish(args, cfg: AppConfig) -> int:
    session = svc.open_session(cfg, args.session)
    report = svc.publish_session(cfg, session, Path(args.output) if args.output else None)
    for rel, reason in report.blocked:
        print(f"HOLD {rel}: {reason}")
    print(f"{len(report.published)} published, {len(report.blocked)} held back, {report.removed_stale} stale removed")
    return 0 if not report.blocked else 2


def _audit(args, cfg: AppConfig) -> int:
    ctx = svc.load_context(cfg, Path(args.source) if args.source else None)
    if not (ctx.terms or ctx.aliases):
        print("warning: no terms or aliases configured, only built-in patterns are checked")
    verdicts = audit_repo(Path(args.repo), ctx)
    for index, v in enumerate(verdicts, 1):
        if v.status is not Status.OK or args.all:
            print(verdict_line(v, index))
    print(totals(verdicts))
    return 1 if any(v.status is Status.FAIL for v in verdicts) else 0


def _stirling_status(args, cfg: AppConfig) -> int:
    status = StirlingEngine(cfg.redaction.engine_settings.get("stirling", {})).client.status()
    print(f"Stirling-PDF reachable: status={status.get('status')} version={status.get('version')}")
    return 0


def add_cli(subparsers) -> None:
    p = subparsers.add_parser("redact", help="redact whole folders (PDF, text/CSV, file names)")
    sub = p.add_subparsers(dest="action", required=True)

    s = sub.add_parser("new", help="create a session: copy SOURCE into a private workspace")
    s.add_argument("source")
    s.add_argument("alias", help="public name of the session (letters, digits, . _ -)")
    s.add_argument("--workspace", help="workspace folder (default: <workspace_root>/<alias>)")
    s.set_defaults(handler=_new)

    s = sub.add_parser("context", help="show or initialise the redaction context of a source folder")
    s.add_argument("source")
    s.add_argument("--init", action="store_true", help="create empty .redaction/terms.txt and aliases.csv")
    s.set_defaults(handler=_context)

    s = sub.add_parser("preview-names", help="write the original -> redacted name mapping (private CSV)")
    s.add_argument("session", help="alias or workspace path")
    s.set_defaults(handler=_preview)

    s = sub.add_parser("run", help="redact and verify every file of the session")
    s.add_argument("session")
    s.add_argument("--force", action="store_true", help="redo files even if nothing changed")
    s.set_defaults(handler=_run)

    s = sub.add_parser("verify", help="verify the redacted files again")
    s.add_argument("session")
    s.set_defaults(handler=_verify)

    s = sub.add_parser("review", help="mark WARN files as visually reviewed")
    s.add_argument("session")
    s.add_argument("paths", nargs="+", help="redacted paths as printed by 'run'")
    s.add_argument("--undo", action="store_true")
    s.set_defaults(handler=_review)

    s = sub.add_parser("publish", help="copy verified files to the output folder")
    s.add_argument("session")
    s.add_argument("--output", help="output root (default: redaction.output_root)")
    s.set_defaults(handler=_publish)

    s = sub.add_parser("audit-repo", help="check files a git repository would publish")
    s.add_argument("repo")
    s.add_argument("--source", help="also apply the context of this source folder")
    s.add_argument("--all", action="store_true", help="list OK files too")
    s.set_defaults(handler=_audit)

    s = sub.add_parser("stirling-status", help="check that the local Stirling-PDF answers")
    s.set_defaults(handler=_stirling_status)


def create_tab(parent, cfg: AppConfig):
    from pdf_toolkit.gui.redaction import RedactionTab

    return RedactionTab(parent, cfg)


MODULE = ToolkitModule(name="redaction", title="Redaction", add_cli=add_cli, create_tab=create_tab)
