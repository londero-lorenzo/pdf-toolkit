"""Text-family engine: CSV/TSV (cell by cell, optional column removal), TXT and Markdown."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from pdf_redaction.engines.base import EngineResult
from pdf_redaction.rules.context import RedactionContext
from pdf_redaction.rules.terms import normalize, read_text
from pdf_redaction.textredact import TextRedactor


def _dialect(sample: str, suffix: str) -> type[csv.Dialect] | csv.Dialect:
    if suffix == ".tsv":
        return csv.excel_tab
    try:
        return csv.Sniffer().sniff(sample[:8192], delimiters=";,\t|")
    except csv.Error:

        class Semicolon(csv.excel):
            delimiter = ";"

        return Semicolon


class TextEngine:
    name = "text"
    version = "1"
    suffixes = frozenset({".csv", ".tsv", ".txt", ".md"})

    def __init__(self, settings: dict | None = None):
        self.settings = settings or {}

    def redact(self, src: Path, dst: Path, ctx: RedactionContext) -> EngineResult:
        redactor = TextRedactor(ctx)
        text = read_text(src)
        suffix = src.suffix.lower()
        if suffix in (".csv", ".tsv"):
            dialect = _dialect(text, suffix)
            rows = list(csv.reader(io.StringIO(text), dialect))
            keep = list(range(max((len(r) for r in rows), default=0)))
            drop = {normalize(c).strip().lower() for c in ctx.drop_columns}
            if rows and drop:
                keep = [i for i in keep if i >= len(rows[0]) or normalize(rows[0][i]).strip().lower() not in drop]
            new_rows = [[redactor.apply(r[i]) if i < len(r) else "" for i in keep] for r in rows]
            buf = io.StringIO()
            csv.writer(buf, dialect=dialect, lineterminator="\n").writerows(new_rows)
            out = buf.getvalue()
        else:
            out = redactor.apply(text)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(out, encoding="utf-8")
        return EngineResult(counts=dict(redactor.counts))
