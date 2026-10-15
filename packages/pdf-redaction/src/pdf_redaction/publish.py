"""Copy verified files from a session to a destination folder.

A file is published when, verified again right now with the current context, it is OK, or WARN
and marked as reviewed. FAIL files, files processed with an older context or from an older version
of the original, and unsupported files are never published. For PDFs a plain-text extract
is written to ``_text/<path>.txt`` and verified as well.

The destination is the exact folder the files go into (no alias sub-folder) and is remembered in
the session. It holds ``.published.json``: the alias that owns the folder and the list of files it
wrote, so a later publish can remove its own stale files and nothing else. Files that pdf-toolkit
did not write are never deleted and never overwritten.
"""

from __future__ import annotations

import contextlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from pdf_core import extract_text
from pdf_redaction.guards import GuardError, ensure_disjoint
from pdf_redaction.ledger import Ledger
from pdf_redaction.rules.context import RedactionContext
from pdf_redaction.session import Session
from pdf_redaction.verify import FileVerdict, Status, scan_text, verify_file

PUBLISHED_FILE = ".published.json"
PUBLISHED_SCHEMA = 2
TEXT_DIR = "_text"
FOREIGN_REASON = "a file not written by pdf-toolkit is in the way"


@dataclass
class PublishReport:
    published: list[str] = field(default_factory=list)
    blocked: list[tuple[str, str]] = field(default_factory=list)  # (redacted path, reason)
    removed_stale: int = 0
    verdicts: list[FileVerdict] = field(default_factory=list)
    foreign_files: int = 0  # files in the destination that pdf-toolkit did not write (left untouched)
    previous_destination: Path | None = None  # set when the destination changed since the last publish
    previous_destination_files: int = 0  # files this session published there that are still present


def published_files(dest: Path, alias: str) -> list[str]:
    """Files ``alias`` published into ``dest`` earlier (relative, posix). Empty if none."""
    path = Path(dest) / PUBLISHED_FILE
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise GuardError("destination has an unreadable .published.json: choose another folder") from None
    if isinstance(data, dict):  # schema 2
        if data.get("alias") != alias:
            raise GuardError("destination holds files published by another session: choose another folder")
        data = data.get("files", [])
    if not isinstance(data, list):  # schema 1: a bare list, written by this alias
        return []
    # never follow an entry out of the destination
    return [f for f in data if isinstance(f, str) and not PurePosixPath(f).is_absolute() and ".." not in f.split("/")]


def foreign_files(dest: Path, alias: str) -> int:
    """How many files in ``dest`` were not written by ``alias``'s publishes (they are never touched)."""
    dest = Path(dest)
    if not dest.is_dir():
        return 0
    own = set(published_files(dest, alias)) | {PUBLISHED_FILE}
    return sum(1 for p in dest.rglob("*") if p.is_file() and p.relative_to(dest).as_posix() not in own)


def publish(
    session: Session,
    ctx: RedactionContext,
    destination: Path,
    *,
    text_extracts: bool = True,
    keep_apart: list[Path] | tuple[Path, ...] = (),
) -> PublishReport:
    """Publish into ``destination`` exactly. It must be disjoint from the source, the workspace and
    every folder in ``keep_apart`` (e.g. the folder holding all workspaces)."""
    dest = Path(destination).expanduser().resolve()
    ensure_disjoint(dest, session.source, "destination", "source")
    ensure_disjoint(dest, session.workspace, "destination", "workspace")
    for other in keep_apart:
        ensure_disjoint(dest, other, "destination", "workspace root")
    previous = published_files(dest, session.alias)  # also refuses a folder owned by another session
    previous_set = set(previous)
    report = PublishReport(foreign_files=foreign_files(dest, session.alias))
    ledger = Ledger(session.ledger_path)
    fingerprint = ctx.fingerprint()
    reviewed = session.reviewed()
    manifest = session.manifest()
    written: list[str] = []

    for entry in sorted(ledger.entries.values(), key=lambda e: e.redacted):
        rel = entry.redacted
        src = session.redacted_dir / rel
        if entry.result != "done" or not src.exists():
            report.blocked.append((rel, "not redacted yet"))
            continue
        if manifest.get(entry.original, {}).get("sha256") != entry.original_sha256:
            report.blocked.append((rel, "source changed since it was redacted: run again"))
            continue
        if entry.context_fingerprint != fingerprint:
            report.blocked.append((rel, "rules changed since it was redacted: run again"))
            continue
        verdict = verify_file(src, PurePosixPath(rel), ctx)
        report.verdicts.append(verdict)
        if verdict.status is Status.FAIL:
            report.blocked.append((rel, "verification FAIL"))
            continue
        if verdict.status is Status.WARN and rel not in reviewed:
            report.blocked.append((rel, "WARN: mark it as reviewed first"))
            continue
        extract = None
        if text_extracts and src.suffix.lower() == ".pdf":
            extract = extract_text(src)
            if any(f.strength.value == "strong" for f in scan_text(extract, ctx, "extract")):
                report.blocked.append((rel, "text extract FAIL"))
                continue
        text_rel = f"{TEXT_DIR}/{rel}.txt" if extract is not None else None
        in_the_way = [r for r in (rel, text_rel) if r and (dest / r).exists() and r not in previous_set]
        if in_the_way:
            report.blocked.append((rel, FOREIGN_REASON))
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        written.append(rel)
        if text_rel is not None:
            (dest / text_rel).parent.mkdir(parents=True, exist_ok=True)
            (dest / text_rel).write_text(extract, encoding="utf-8")
            written.append(text_rel)
        report.published.append(rel)

    for rel in set(previous) - set(written):
        stale = dest / rel
        if stale.is_file():
            stale.unlink()
            report.removed_stale += 1
    if written or previous:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / PUBLISHED_FILE).write_text(
            json.dumps({"schema": PUBLISHED_SCHEMA, "alias": session.alias, "files": sorted(written)}, indent=1),
            encoding="utf-8",
        )

    last = session.destination
    if last is not None and last.resolve() != dest:
        report.previous_destination = last
        with contextlib.suppress(GuardError):  # if the old folder now belongs to someone else, count nothing
            report.previous_destination_files = sum(
                1 for rel in published_files(last, session.alias) if (last / rel).is_file()
            )
    session.set_destination(dest)
    return report
