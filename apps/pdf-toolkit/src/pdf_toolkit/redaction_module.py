"""The ``redact`` command family and the Redaction tab."""

from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath

from pdf_redaction.audit import audit_repo
from pdf_redaction.engines.stirling import StirlingEngine
from pdf_redaction.rules.context import ALIASES_FILENAME, TERMS_FILENAME, context_dir
from pdf_redaction.rules.terms import write_aliases, write_terms
from pdf_redaction.verify import Status, Strength, scan_path
from pdf_toolkit import redaction_service as svc
from pdf_toolkit.config import AppConfig
from pdf_toolkit.modules import ToolkitModule
from pdf_toolkit.safety import exit_code, safe_folder, totals, verdict_line


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
            note = svc.manual_note(item)
            print(verdict_line(item.verdict, index, item.redacted in reviewed) + (f" [{note}]" if note else ""))
    if report.context_changed:
        print(f"note: rules changed since the last run, {report.context_changed} files were redone")
    if manual := svc.manual_summary(report):
        print(manual)
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
    manual = svc.manual_state(session)
    for index, v in enumerate(verdicts, 1):
        note = manual.get(v.rel_path)
        print(verdict_line(v, index, v.rel_path in reviewed) + (f" [{note}]" if note else ""))
    print(totals(verdicts))
    return exit_code(verdicts)


def _reset_manual(args, cfg: AppConfig) -> int:
    session = svc.open_session(cfg, args.session)
    paths = [p.replace("\\", "/") for p in args.paths]  # accept Windows separators
    unknown = [p for p in paths if p not in svc.known_redacted_paths(session)]
    if unknown:
        print(f"{len(unknown)} path(s) not found among the redacted files (use the paths printed by 'run')")
        return 1
    count = svc.discard_manual(session, paths or None)
    print(f"{count} manual edit(s) discarded: the next 'run' redoes those files from the originals")
    return 0


def _review(args, cfg: AppConfig) -> int:
    session = svc.open_session(cfg, args.session)
    paths = [p.replace("\\", "/") for p in args.paths]  # accept Windows separators
    known = {v.rel_path: v for v in svc.verify(cfg, session)}
    unknown = [p for p in paths if p not in known]
    if unknown:
        print(f"{len(unknown)} path(s) not found among the redacted files (use the paths printed by 'run')")
        return 1
    session.set_reviewed(paths, not args.undo)
    print(f"{len(paths)} file(s) {'un' if args.undo else ''}marked as reviewed")
    return 0


def _publish(args, cfg: AppConfig) -> int:
    session = svc.open_session(cfg, args.session)
    ctx = svc.load_context(cfg, session.source)
    if args.to:
        target, origin = Path(args.to), "--to"
    else:
        target = svc.default_destination(cfg, session)
        origin = "last used" if session.destination else "output_root/<alias>"
    if target:
        print(f"destination ({origin}): {safe_folder(target, ctx)}")
    report = svc.publish_session(cfg, session, target)
    for index, (rel, reason) in enumerate(report.blocked, 1):
        leaks = any(f.strength is Strength.STRONG for f in scan_path(PurePosixPath(rel), ctx))
        print(f"HOLD {f'file#{index}' if leaks else rel}: {reason}")
    print(f"{len(report.published)} published, {len(report.blocked)} held back, {report.removed_stale} stale removed")
    if report.foreign_files:
        print(f"note: the destination holds {report.foreign_files} file(s) not written by pdf-toolkit: left untouched")
    if report.previous_destination:
        print(
            "note: destination changed; the previous one was left as it was: "
            f"{safe_folder(report.previous_destination, ctx)} "
            f"({report.previous_destination_files} file(s) published there)"
        )
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


SESSION_ARG = "session alias given to 'new', or the workspace folder"

GUIDE = "Full guide: docs/redaction-guide.md"

NEW_HELP = f"""Create a session: copy SOURCE into a private workspace. Nothing is redacted yet.

Run it once per source folder; later changes in SOURCE are picked up by 'run'.
The workspace is <workspace_root>/<ALIAS> unless --workspace is given; it holds the
unredacted copy, so it must not be inside SOURCE, output_root or a protected location.
The ALIAS also names the default publish folder, <output_root>/<ALIAS>.

examples:
  pdf-toolkit redact new "D:/originals/2025" invoices-2025
  pdf-toolkit redact new "D:/originals/2025" invoices-2025 --workspace "E:/private/ws"

{GUIDE}"""

RUN_HELP = f"""Redact and verify every file of a session, then print one line per file.

Steps: copy changes from SOURCE -> load the context (global lists + SOURCE/.redaction/)
-> redact names -> redact contents (.pdf via Stirling-PDF; .csv .tsv .txt .md built in;
other types are skipped and never published) -> verify each output.
Incremental: files whose original, rules and engine settings did not change are only verified.

output lines:
  OK   <redacted path>                    nothing found
  WARN <path>: images on p1               a person must look at it, then 'redact review'
  FAIL <path>: p2: term folder#2 x1       still matches line 2 of .redaction/terms.txt
  SKIP / ERR                              not processed / engine error (never published)
  file#N replaces a path that still matches a rule. Matched text is never printed.

manual edits: if you edit a redacted file by hand (e.g. boxes drawn in Stirling-PDF, saved
over the file in redacted/), the next run keeps it as the base of that file and applies the
rules on top: lines end with [manual edits kept]. It is dropped, and the file redone from the
original, when a rule is removed or the original changes ([manual edits dropped: <reason>]);
'reset-manual' drops it on purpose.

exit codes: 0 all OK, 2 some WARN, 1 any FAIL or error

examples:
  pdf-toolkit redact run invoices-2025
  pdf-toolkit redact run "E:/private/ws" --force

{GUIDE}"""

REVIEW_HELP = f"""Record that you looked at WARN files yourself and they are safe to publish.

WARN means the checks cannot decide alone: pages with images or scans, weak hits such
as long numbers, annotations, forms, attachments. Open the file in the workspace
(redacted/<path>), check it, then mark it. 'publish' copies a WARN file only if marked.
The mark is bound to the file's content: if a later 'run' produces a different file,
it is not reviewed any more. 'run' and 'verify' show "(reviewed)" next to marked files.

PATH is the redacted path exactly as printed by 'run' (quote it if it has spaces).
exit codes: 0 marked, 1 a path is not among the redacted files

examples:
  pdf-toolkit redact review invoices-2025 "ABCDEPOL-A.pdf" "scans/receipt 03.pdf"
  pdf-toolkit redact review invoices-2025 "ABCDEPOL-A.pdf" --undo

{GUIDE}"""

RESET_MANUAL_HELP = f"""Discard manual edits: the next 'run' redoes those files from the originals.

A redacted file edited by hand after a run (e.g. boxes drawn in Stirling-PDF) is kept as the
base of that file by later runs. Use this to start over from the original instead: the copy
of the edit kept in the workspace (manual/) is deleted.

PATH is the redacted path exactly as printed by 'run'; without PATH every edit is discarded.
exit codes: 0 done, 1 a path is not among the redacted files

examples:
  pdf-toolkit redact reset-manual invoices-2025 "ABCDEPOL-A.pdf"
  pdf-toolkit redact reset-manual invoices-2025

{GUIDE}"""

PUBLISH_HELP = f"""Copy the files that are safe to share into a destination folder.

Nothing is redacted here: run 'run' first. Each file is verified again with the current
rules and copied only if OK, or WARN and reviewed. Held back: FAIL, WARN not reviewed,
files redacted with older rules, files edited by hand since the last run, skipped types,
errors. Next to each PDF a text extract is written to _text/<path>.txt.

The destination is the exact folder the files go into (no <ALIAS> sub-folder). Without --to
it is the one used last time by this session; the first time, <output_root>/<ALIAS> if
output_root is set, else --to is required. It must not contain or be inside SOURCE, the
workspace or workspace_root.

Run it again whenever you like: the destination is brought in line with the session, and
files this session published there earlier that no longer qualify are removed. Files that
pdf-toolkit did not write are never deleted or overwritten (a file with the same name is
held back). If you publish somewhere else, the previous folder is left as it was and
reported.

output lines:
  destination (--to): E:/to-share
  HOLD <path>: WARN: mark it as reviewed first
  3 published, 1 held back, 0 stale removed
exit codes: 0 everything published, 2 something held back

examples:
  pdf-toolkit redact publish invoices-2025 --to "E:/to-share"
  pdf-toolkit redact publish invoices-2025

{GUIDE}"""


def add_cli(subparsers) -> None:
    raw = argparse.RawDescriptionHelpFormatter
    p = subparsers.add_parser("redact", help="redact whole folders (PDF, text/CSV, file names)", epilog=GUIDE)
    sub = p.add_subparsers(dest="action", required=True)

    s = sub.add_parser(
        "new", help="create a session: copy SOURCE into a private workspace", description=NEW_HELP, formatter_class=raw
    )
    s.add_argument("source", help="folder of originals (only read; sub-folders included, .redaction/ excluded)")
    s.add_argument(
        "alias",
        help="public session name, 1-64 letters, digits, . _ - (e.g. invoices-2025). It names the workspace "
        "and the default publish folder, so it must not contain personal data",
    )
    s.add_argument("--workspace", help="workspace folder (default: <workspace_root>/<alias>)")
    s.set_defaults(handler=_new)

    s = sub.add_parser("context", help="show or initialise the redaction context of a source folder")
    s.add_argument("source")
    s.add_argument("--init", action="store_true", help="create empty .redaction/terms.txt and aliases.csv")
    s.set_defaults(handler=_context)

    s = sub.add_parser("preview-names", help="write the original -> redacted name mapping (private CSV)")
    s.add_argument("session", help=SESSION_ARG)
    s.set_defaults(handler=_preview)

    s = sub.add_parser(
        "run", help="redact and verify every file of the session", description=RUN_HELP, formatter_class=raw
    )
    s.add_argument("session", help=SESSION_ARG)
    s.add_argument(
        "--force",
        action="store_true",
        help="redo every file even if nothing changed (e.g. after upgrading Stirling-PDF)",
    )
    s.set_defaults(handler=_run)

    s = sub.add_parser("verify", help="verify the redacted files again")
    s.add_argument("session", help=SESSION_ARG)
    s.set_defaults(handler=_verify)

    s = sub.add_parser("review", help="mark WARN files as checked by you", description=REVIEW_HELP, formatter_class=raw)
    s.add_argument("session", help=SESSION_ARG)
    s.add_argument("paths", nargs="+", metavar="PATH", help="redacted path as printed by 'run' (one or more)")
    s.add_argument("--undo", action="store_true", help="remove the mark")
    s.set_defaults(handler=_review)

    s = sub.add_parser(
        "reset-manual",
        help="discard manual edits: the next run redoes those files from the originals",
        description=RESET_MANUAL_HELP,
        formatter_class=raw,
    )
    s.add_argument("session", help=SESSION_ARG)
    s.add_argument("paths", nargs="*", metavar="PATH", help="redacted path as printed by 'run' (default: every file)")
    s.set_defaults(handler=_reset_manual)

    s = sub.add_parser(
        "publish", help="copy verified files to the output folder", description=PUBLISH_HELP, formatter_class=raw
    )
    s.add_argument("session", help=SESSION_ARG)
    s.add_argument(
        "--to",
        metavar="FOLDER",
        help="publish exactly into FOLDER and remember it for this session "
        "(default: the last destination, else <output_root>/<alias>)",
    )
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
