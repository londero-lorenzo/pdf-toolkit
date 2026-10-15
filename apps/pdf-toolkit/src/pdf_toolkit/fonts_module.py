"""``pdf-toolkit fonts``: which PDFs use fonts whose text cannot be extracted reliably.

Console lines name files as ``file#N`` only (an original file name may be private); the matching
paths go to the optional ``--csv`` report, which is private like the files themselves.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Iterator
from pathlib import Path

from pdf_fonts import FontIssue, FontKind, FontReport, fonttools_available, scan_fonts
from pdf_redaction.guards import ensure_not_within
from pdf_toolkit.config import AppConfig
from pdf_toolkit.modules import ToolkitModule
from pdf_toolkit.redaction_service import protected

SCAN_HELP = """\
Read every PDF under the given files or folders (sub-folders included, .redaction/ excluded)
and report the fonts that make text extraction unreliable. Nothing is modified.

status:
  OK    nothing to report
  NOTE  CFF fonts with their own encoding (decoded through fontTools) or fonts not embedded
  RISK  fonts without a Unicode map (Type0 Identity, Type3): the extracted text, and so the
        redaction check, may miss words on those pages; check them visually. Also unreadable
        or encrypted files, and CFF fonts when fontTools is missing

output lines:
  fontTools: installed
  NOTE file#2: 3 fonts; 1 CFF with its own encoding (p1-3): decoded through fontTools
  RISK file#3: 2 fonts; 2 without Unicode map (p2): extracted text unreliable, check visually
  --- 3 files: 1 OK, 1 NOTE, 1 RISK
exit codes: 0 no RISK, 2 at least one RISK

Files are named file#N on the console. --csv writes N, path and counts per file: keep it
private, like the PDFs.

examples:
  pdf-toolkit fonts scan "D:/documents/invoices"
  pdf-toolkit fonts scan "D:/documents/invoices" --csv "D:/private/fonts.csv"
"""


def _pdf_files(roots: list[Path]) -> Iterator[tuple[Path, str]]:
    """(file, path shown in the private report) for every PDF to scan."""
    for root in roots:
        if root.is_dir():
            for f in sorted(root.rglob("*")):
                rel = f.relative_to(root)
                if f.is_file() and f.suffix.lower() == ".pdf" and ".redaction" not in rel.parts:
                    yield f, rel.as_posix()
        else:
            yield root, root.name


def _pages(numbers: list[int]) -> str:
    """[1, 2, 3, 5] -> 'p1-3, p5'."""
    runs: list[list[int]] = []
    for n in numbers:
        if runs and n == runs[-1][-1] + 1:
            runs[-1].append(n)
        else:
            runs.append([n])
    return ", ".join(f"p{r[0]}" if len(r) == 1 else f"p{r[0]}-{r[-1]}" for r in runs)


def assess(report: FontReport, fonttools: bool) -> tuple[str, str]:
    """(status, detail) of one file; the detail holds counts, issue kinds and pages only."""
    if report.error:
        return "RISK", f"unreadable ({report.error})"
    if report.encrypted:
        return "RISK", "encrypted: fonts not checked"
    status, parts = "OK", [f"{len(report.fonts)} fonts"]
    if blind := report.with_issue(FontIssue.NO_UNICODE_MAP):
        status = "RISK"
        pages = _pages(report.pages_with(FontIssue.NO_UNICODE_MAP))
        parts.append(f"{len(blind)} without Unicode map ({pages}): extracted text unreliable, check visually")
    if cff := report.with_issue(FontIssue.CFF_CUSTOM_ENCODING):
        pages = _pages(report.pages_with(FontIssue.CFF_CUSTOM_ENCODING))
        if fonttools:
            status = "NOTE" if status == "OK" else status
            parts.append(f"{len(cff)} CFF with its own encoding ({pages}): decoded through fontTools")
        else:
            status = "RISK"
            parts.append(f"{len(cff)} CFF with its own encoding ({pages}): not decoded, install fontTools")
    if missing := report.with_issue(FontIssue.NOT_EMBEDDED):
        status = "NOTE" if status == "OK" else status
        parts.append(f"{len(missing)} not embedded")
    return status, "; ".join(parts)


def _scan(args, cfg: AppConfig) -> int:
    roots = [Path(p) for p in args.paths]
    for index, root in enumerate(roots, 1):
        if not root.exists():
            print(f"error: PATH #{index} does not exist", file=sys.stderr)
            return 1
    out = Path(args.csv) if args.csv else None
    if out:
        ensure_not_within(out, protected(cfg), "font report")
    fonttools = fonttools_available()
    print(f"fontTools: {'installed' if fonttools else 'missing (CFF fonts with their own encoding are not decoded)'}")
    rows = []
    counts = {"OK": 0, "NOTE": 0, "RISK": 0}
    for index, (path, shown) in enumerate(_pdf_files(roots), 1):
        report = scan_fonts(path)
        status, detail = assess(report, fonttools)
        counts[status] += 1
        print(f"{status:<4} file#{index}: {detail}")
        kinds = report.kind_counts()
        rows.append(
            [index, shown, status, len(report.fonts)]
            + [kinds[k] for k in FontKind]
            + [len(report.with_issue(i)) for i in FontIssue]
            + [
                _pages(report.pages_with(FontIssue.NO_UNICODE_MAP)),
                report.error or ("encrypted" if report.encrypted else ""),
            ]
        )
    print(f"--- {len(rows)} files: {counts['OK']} OK, {counts['NOTE']} NOTE, {counts['RISK']} RISK")
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh, delimiter=";")
            writer.writerow(
                ["file", "path", "status", "fonts", *FontKind, *FontIssue, "pages to check visually", "error"]
            )
            writer.writerows(rows)
        print(f"private report written: {len(rows)} rows")
    return 2 if counts["RISK"] else 0


def add_cli(subparsers) -> None:
    p = subparsers.add_parser("fonts", help="check which PDFs use fonts whose text cannot be extracted reliably")
    sub = p.add_subparsers(dest="action", required=True)
    s = sub.add_parser(
        "scan",
        help="report fonts per PDF (read only)",
        description=SCAN_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument("paths", nargs="+", metavar="PATH", help="PDF file or folder (one or more)")
    s.add_argument("--csv", metavar="FILE", help="also write a private CSV report with the paths")
    s.set_defaults(handler=_scan)


MODULE = ToolkitModule(name="fonts", title="Fonts", add_cli=add_cli)
