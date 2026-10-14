"""Check the files tracked by a git repository against a redaction context.

Meant for people who publish code next to private documents: run it before ``git push`` to be
sure no term, alias or PII pattern slipped into the repository (file contents and paths).
Only categories and counts are reported.
"""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath

from pdf_redaction.rules.context import RedactionContext
from pdf_redaction.verify import SUPPORTED_SUFFIXES, FileVerdict, scan_path, scan_text, verify_file

MAX_TEXT_BYTES = 5 * 1024 * 1024


def tracked_files(repo: Path) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        check=True,
    ).stdout
    return sorted(p for p in out.decode("utf-8", errors="replace").split("\0") if p)


def audit_repo(repo: Path, ctx: RedactionContext) -> list[FileVerdict]:
    """Tracked and untracked-but-not-ignored files: everything a ``git add -A`` would publish."""
    repo = Path(repo)
    verdicts = []
    for rel in tracked_files(repo):
        path = repo / rel
        if not path.is_file():
            continue
        if path.suffix.lower() in SUPPORTED_SUFFIXES:
            verdicts.append(verify_file(path, PurePosixPath(rel), ctx))
            continue
        verdict = FileVerdict(rel, findings=scan_path(PurePosixPath(rel), ctx))
        if path.stat().st_size <= MAX_TEXT_BYTES:
            data = path.read_bytes()
            if b"\0" not in data[:8192]:  # looks like text (source code, config, docs)
                verdict.findings += scan_text(data.decode("utf-8", errors="replace"), ctx, "text")
            else:
                verdict.notes.append("binary file: not inspected")
        else:
            verdict.notes.append("large file: not inspected")
        verdicts.append(verdict)
    return verdicts
