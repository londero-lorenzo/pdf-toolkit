"""Console-safe reporting.

Anything printed may end up in a terminal log, a screen share or an AI assistant's context.
Lines produced here contain only status, rule labels, counts and *redacted* paths; a redacted
path that still triggers a rule is replaced by ``file#N``.
"""

from __future__ import annotations

from pdf_redaction.verify import FileVerdict, Status


def safe_label(verdict: FileVerdict, index: int) -> str:
    return f"file#{index}" if verdict.path_has_hits else verdict.rel_path


def verdict_line(verdict: FileVerdict, index: int, reviewed: bool = False) -> str:
    status = verdict.status.value
    mark = " (reviewed)" if reviewed and verdict.status is Status.WARN else ""
    detail = verdict.summary()
    return f"{status:<4} {safe_label(verdict, index)}{mark}" + (f": {detail}" if detail else "")


def totals(verdicts: list[FileVerdict]) -> str:
    counts = {s: sum(1 for v in verdicts if v.status is s) for s in Status}
    return f"--- {len(verdicts)} files: {counts[Status.OK]} OK, {counts[Status.WARN]} WARN, {counts[Status.FAIL]} FAIL"


def exit_code(verdicts: list[FileVerdict]) -> int:
    if any(v.status is Status.FAIL for v in verdicts):
        return 1
    return 2 if any(v.status is Status.WARN for v in verdicts) else 0
