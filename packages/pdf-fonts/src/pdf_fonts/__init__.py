"""Font analysis for PDFs.

Today read-only: which fonts a document uses and whether its text can be extracted reliably.
Font work that writes PDFs (e.g. adding a missing /ToUnicode map) belongs here, never in pdf-core.

Privacy rule: results carry font kinds, issue codes, counts and page numbers only, never font
names or text, since a custom font name can identify the organisation a document comes from.
"""

from pdf_fonts.scan import FontEntry, FontIssue, FontKind, FontReport, fonttools_available, scan_fonts

__all__ = ["FontEntry", "FontIssue", "FontKind", "FontReport", "fonttools_available", "scan_fonts"]
__version__ = "0.1.0"
