"""Tiny synthetic-PDF writer for tests and demos (pure Python, no dependencies).

Only for fixtures: it lets every test build its own documents, so no real document ever has to
be stored in the repository.
"""

from __future__ import annotations

import zlib
from collections.abc import Sequence
from pathlib import Path


def _pdf_string(text: str) -> bytes:
    raw = text.encode("cp1252", errors="replace")
    return b"(" + raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


def make_pdf(
    path: str | Path,
    pages: Sequence[Sequence[str]],
    *,
    image_pages: Sequence[int] = (),
    info: dict[str, str] | None = None,
    font_size: int = 11,
) -> Path:
    """Write a PDF with one text line per entry, Helvetica, A4.

    ``image_pages`` are 1-based page numbers that receive a small grey image.
    ``info`` fills the document information dictionary (e.g. ``{"Author": "..."}``).
    """
    path = Path(path)
    objects: list[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    catalog_id = add(b"")  # placeholders, filled below
    pages_id = add(b"")
    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    pixels = zlib.compress(bytes([128] * 16 * 16))
    image_id = add(
        b"<< /Type /XObject /Subtype /Image /Width 16 /Height 16 /ColorSpace /DeviceGray "
        b"/BitsPerComponent 8 /Filter /FlateDecode /Length "
        + str(len(pixels)).encode()
        + b" >>\nstream\n"
        + pixels
        + b"\nendstream"
    )

    page_ids = []
    for number, lines in enumerate(pages, 1):
        ops = [b"BT", f"/F1 {font_size} Tf".encode(), f"{font_size + 4} TL".encode(), b"56 790 Td"]
        for line in lines:
            ops.append(_pdf_string(line) + b" Tj T*")
        ops.append(b"ET")
        resources = b"/Font << /F1 " + f"{font_id} 0 R".encode() + b" >>"
        if number in image_pages:
            ops.append(b"q 64 0 0 64 460 700 cm /Im1 Do Q")
            resources += b" /XObject << /Im1 " + f"{image_id} 0 R".encode() + b" >>"
        content = b"\n".join(ops)
        content_id = add(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream")
        page_ids.append(
            add(
                b"<< /Type /Page /Parent " + f"{pages_id} 0 R".encode() + b" /MediaBox [0 0 595 842]"
                b" /Resources << " + resources + b" >> /Contents " + f"{content_id} 0 R".encode() + b" >>"
            )
        )

    kids = b" ".join(f"{i} 0 R".encode() for i in page_ids)
    objects[pages_id - 1] = b"<< /Type /Pages /Kids [" + kids + b"] /Count " + str(len(page_ids)).encode() + b" >>"
    objects[catalog_id - 1] = b"<< /Type /Catalog /Pages " + f"{pages_id} 0 R".encode() + b" >>"
    info_id = None
    if info:
        entries = b" ".join(b"/" + k.encode("ascii") + b" " + _pdf_string(v) for k, v in info.items())
        info_id = add(b"<< " + entries + b" >>")

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    trailer = f"<< /Size {len(objects) + 1} /Root {catalog_id} 0 R".encode()
    if info_id:
        trailer += f" /Info {info_id} 0 R".encode()
    out += b"trailer\n" + trailer + b" >>\nstartxref\n" + str(xref).encode() + b"\n%%EOF\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))
    return path
