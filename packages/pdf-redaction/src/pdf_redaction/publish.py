"""Copy verified files from a session to an output folder.

A file is published when, verified again right now with the current context, it is OK, or WARN
and marked as reviewed. FAIL files, files processed with an older context or from an older version
of the original, and unsupported files are never published. For PDFs a plain-text extract is
written to ``_text/<path>.txt`` and verified as well.

Output layout: ``<output root>/<alias>/...`` plus ``.published.json``, the list of files this
session wrote, so a later publish can remove its own stale files and nothing else.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from pdf_core import extract_text
from pdf_redaction.guards import ensure_disjoint
from pdf_redaction.ledger import Ledger
from pdf_redaction.rules.context import RedactionContext
from pdf_redaction.session import Session
from pdf_redaction.verify import FileVerdict, Status, scan_text, verify_file

PUBLISHED_FILE = ".published.json"
TEXT_DIR = "_text"


@dataclass
class PublishReport:
    published: list[str] = field(default_factory=list)
    blocked: list[tuple[str, str]] = field(default_factory=list)  # (redacted path, reason)
    removed_stale: int = 0
    verdicts: list[FileVerdict] = field(default_factory=list)


def publish(session: Session, ctx: RedactionContext, output_root: Path, *, text_extracts: bool = True) -> PublishReport:
    output_root = Path(output_root)
    ensure_disjoint(output_root, session.source, "output", "source")
    ensure_disjoint(output_root, session.workspace, "output", "workspace")
    dest = output_root / session.alias
    report = PublishReport()
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
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        written.append(rel)
        if extract is not None:
            text_rel = f"{TEXT_DIR}/{rel}.txt"
            (dest / text_rel).parent.mkdir(parents=True, exist_ok=True)
            (dest / text_rel).write_text(extract, encoding="utf-8")
            written.append(text_rel)
        report.published.append(rel)

    previous_file = dest / PUBLISHED_FILE
    previous = json.loads(previous_file.read_text(encoding="utf-8")) if previous_file.exists() else []
    for rel in set(previous) - set(written):
        stale = dest / rel
        if stale.is_file():
            stale.unlink()
            report.removed_stale += 1
    if written or previous:
        dest.mkdir(parents=True, exist_ok=True)
        previous_file.write_text(json.dumps(sorted(written), indent=1), encoding="utf-8")
    return report
