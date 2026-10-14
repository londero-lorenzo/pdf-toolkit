"""Check that a redacted file (content, metadata and path) no longer contains any rule hit.

Verdicts carry categories and counts only, never the text that matched.

Status:
- FAIL: a strong rule still matches, the file is encrypted/unreadable, or its type cannot be checked;
- WARN: weak hits or things a human must look at (images, no extractable text, annotations, forms,
  attachments, XMP metadata). A WARN file can be published only after it is marked as reviewed;
- OK: nothing found.

PDFs are read with every available pdf-core backend (pypdf and, when installed, PDFium): two
independent extractors make it harder for leftover text to go unnoticed.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePath

from pdf_core import available_backends, inspect_pdf
from pdf_redaction.names import NameRedactor
from pdf_redaction.rules.context import RedactionContext
from pdf_redaction.rules.patterns import Strength
from pdf_redaction.rules.terms import normalize, read_text

TEXT_SUFFIXES = {".txt", ".md", ".csv", ".tsv"}
PDF_SUFFIXES = {".pdf"}
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | PDF_SUFFIXES


class Status(StrEnum):
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True)
class Finding:
    where: str  # "p3", "metadata", "name", ...
    rule: str  # rule label, e.g. "term folder#2" or "EMAIL"
    strength: Strength
    count: int


@dataclass
class FileVerdict:
    rel_path: str  # redacted relative path (posix)
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # reasons for a human review
    errors: list[str] = field(default_factory=list)  # reasons that block publishing
    image_pages: list[int] = field(default_factory=list)

    @property
    def status(self) -> Status:
        if self.errors or any(f.strength is Strength.STRONG for f in self.findings):
            return Status.FAIL
        if self.notes or self.findings:
            return Status.WARN
        return Status.OK

    @property
    def path_has_hits(self) -> bool:
        return any(f.where == "name" and f.strength is Strength.STRONG for f in self.findings)

    def summary(self) -> str:
        parts = [f"{f.where}: {f.rule} x{f.count}" for f in self.findings]
        return "; ".join(parts + self.notes + self.errors)


def scan_text(text: str, ctx: RedactionContext, where: str) -> list[Finding]:
    text = normalize(text)
    out = []
    for m in ctx.matchers():
        n = len(m.regex.findall(text))
        if n:
            out.append(Finding(where, m.label, m.strength, n))
    return out


def scan_path(rel_path: PurePath, ctx: RedactionContext) -> list[Finding]:
    redactor = NameRedactor(ctx)
    counts: dict[tuple[str, Strength], int] = {}
    for part in PurePath(rel_path).parts:
        for label, strength in redactor.findings(part):
            counts[(label, strength)] = counts.get((label, strength), 0) + 1
    return [Finding("name", label, strength, n) for (label, strength), n in counts.items()]


def _merge(findings: list[Finding]) -> list[Finding]:
    """Same (where, rule) from two backends: keep the highest count."""
    best: dict[tuple[str, str], Finding] = {}
    for f in findings:
        key = (f.where, f.rule)
        if key not in best or f.count > best[key].count:
            best[key] = f
    return list(best.values())


def _verify_pdf(path: Path, ctx: RedactionContext, verdict: FileVerdict) -> None:
    findings: list[Finding] = []
    for backend in available_backends():
        try:
            report = inspect_pdf(path, backend)
        except Exception as exc:
            verdict.errors.append(f"unreadable with {backend} ({type(exc).__name__})")
            continue
        if report.encrypted:
            verdict.errors.append("encrypted PDF: cannot be verified")
            return
        for where, text in report.text_chunks():
            findings += scan_text(text, ctx, where)
        if backend != "pypdf":
            continue
        if report.image_pages:
            verdict.image_pages = report.image_pages
            verdict.notes.append("images on " + ", ".join(f"p{n}" for n in report.image_pages))
        if not report.has_text:
            verdict.notes.append("no extractable text (scan or image only): visual check needed")
        annotated = [p.number for p in report.pages if p.annotation_count]
        if annotated:
            verdict.notes.append("annotations on " + ", ".join(f"p{n}" for n in annotated))
        if report.form_field_count:
            verdict.notes.append(f"{report.form_field_count} form fields")
        if report.embedded_file_count:
            verdict.notes.append(f"{report.embedded_file_count} embedded files")
        if report.has_xmp:
            verdict.notes.append("XMP metadata present")
    verdict.findings += _merge(findings)


def verify_file(path: Path, rel_path: PurePath, ctx: RedactionContext) -> FileVerdict:
    verdict = FileVerdict(PurePath(rel_path).as_posix())
    verdict.findings += scan_path(rel_path, ctx)
    suffix = Path(path).suffix.lower()
    try:
        if suffix in PDF_SUFFIXES:
            _verify_pdf(Path(path), ctx, verdict)
        elif suffix in TEXT_SUFFIXES:
            text = read_text(Path(path))
            found = scan_text(text, ctx, "text")
            if suffix in (".csv", ".tsv"):
                # also cell by cell, one per line: catches e.g. a first and last name in adjacent columns
                delimiter = "\t" if suffix == ".tsv" else (";" if text.count(";") > text.count(",") else ",")
                cells = "\n".join(c for row in csv.reader(io.StringIO(text), delimiter=delimiter) for c in row)
                found += scan_text(cells, ctx, "text")
            verdict.findings += _merge(found)
        else:
            verdict.errors.append(f"type {suffix or '(none)'} cannot be verified")
    except Exception as exc:
        verdict.errors.append(f"read error ({type(exc).__name__})")
    return verdict


def verify_tree(root: Path, ctx: RedactionContext) -> list[FileVerdict]:
    root = Path(root)
    files = sorted(p for p in root.rglob("*") if p.is_file())
    return [verify_file(p, p.relative_to(root), ctx) for p in files]
