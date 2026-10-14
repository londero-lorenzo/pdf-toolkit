"""Optional backend based on pypdfium2 (PDFium). Install with ``pdf-core[pdfium]``.

It covers page text, images, annotation counts, document info and attachments. XMP and form
values are left to the pypdf backend.

PDFium is not thread-safe: every call into it goes through ``_LOCK``, so callers may use this
backend from several threads (the redaction pipeline verifies files in parallel).
"""

from __future__ import annotations

import threading
from pathlib import Path

from pdf_core.inspect import PageInfo, PdfReport

_TECHNICAL_INFO_KEYS = {"CreationDate", "ModDate", "Trapped"}
_LOCK = threading.RLock()


def inspect(path: Path) -> PdfReport:
    with _LOCK:
        return _inspect(path)


def _inspect(path: Path) -> PdfReport:
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c

    try:
        pdf = pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError as exc:
        if "password" in str(exc).lower():
            return PdfReport(backend="pdfium", encrypted=True)
        raise
    try:
        pages = []
        for index in range(len(pdf)):
            page = pdf[index]
            try:
                textpage = page.get_textpage()
                try:
                    text = textpage.get_text_bounded()
                finally:
                    textpage.close()
                images = sum(1 for _ in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=15))
                annots = pdfium_c.FPDFPage_GetAnnotCount(page.raw)
            finally:
                page.close()
            pages.append(PageInfo(number=index + 1, text=text, image_count=images, annotation_count=annots))
        info = pdf.get_metadata_dict(skip_empty=True)
        metadata = "\n".join(str(v) for k, v in info.items() if k not in _TECHNICAL_INFO_KEYS)
        return PdfReport(
            backend="pdfium",
            pages=pages,
            metadata_text=metadata,
            embedded_file_count=pdf.count_attachments(),
        )
    finally:
        pdf.close()
