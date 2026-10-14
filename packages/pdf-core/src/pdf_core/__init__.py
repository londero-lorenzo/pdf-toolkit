"""Read-only PDF inspection. Nothing in this package writes or modifies a PDF."""

from pdf_core.inspect import (
    PageInfo,
    PdfReport,
    available_backends,
    extract_text,
    inspect_pdf,
)

__all__ = ["PageInfo", "PdfReport", "available_backends", "extract_text", "inspect_pdf"]
__version__ = "0.1.0"
