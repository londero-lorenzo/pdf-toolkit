"""Backend-independent PDF report: what a PDF contains, page by page."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class PageInfo:
    number: int  # 1-based
    text: str
    image_count: int = 0
    annotation_count: int = 0
    annotation_text: str = ""  # /Contents and /T of annotations (comments, form widgets...)


@dataclass(frozen=True)
class PdfReport:
    backend: str
    encrypted: bool = False
    pages: list[PageInfo] = field(default_factory=list)
    metadata_text: str = ""  # document info values, excluding technical dates
    has_xmp: bool = False
    form_field_count: int = 0
    form_text: str = ""  # field names and values
    embedded_file_count: int = 0

    @property
    def has_text(self) -> bool:
        return any(p.text.strip() for p in self.pages)

    @property
    def image_pages(self) -> list[int]:
        return [p.number for p in self.pages if p.image_count]

    def text_chunks(self) -> Iterable[tuple[str, str]]:
        """(where, text) pairs covering every piece of extractable text in the report."""
        for p in self.pages:
            yield f"p{p.number}", p.text
            if p.annotation_text:
                yield f"p{p.number} annotations", p.annotation_text
        if self.metadata_text:
            yield "metadata", self.metadata_text
        if self.form_text:
            yield "form fields", self.form_text


def available_backends() -> list[str]:
    names = ["pypdf"]
    try:
        import pypdfium2  # noqa: F401
    except ImportError:
        pass
    else:
        names.append("pdfium")
    return names


def inspect_pdf(path: str | Path, backend: str = "pypdf") -> PdfReport:
    path = Path(path)
    if backend == "pypdf":
        from pdf_core.backends.pypdf_backend import inspect as run
    elif backend == "pdfium":
        from pdf_core.backends.pdfium_backend import inspect as run
    else:
        raise ValueError(f"unknown backend: {backend}")
    return run(path)


def extract_text(path: str | Path, backend: str = "pypdf") -> str:
    """Plain text of all pages, separated by form feeds."""
    return "\f".join(p.text for p in inspect_pdf(path, backend).pages)
