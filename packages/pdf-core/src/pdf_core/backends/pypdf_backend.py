"""Default backend, based on pypdf (BSD-3-Clause)."""

from __future__ import annotations

import contextlib
import re
from pathlib import Path

from pypdf import PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject

from pdf_core.inspect import PageInfo, PdfReport

_TECHNICAL_INFO_KEYS = {"/CreationDate", "/ModDate", "/Trapped"}
_XML_TAG = re.compile(r"<[^>]+>")


def _resolve(obj):
    return obj.get_object() if isinstance(obj, IndirectObject) else obj


def _count_xobject_images(resources, seen: set[int]) -> int:
    resources = _resolve(resources)
    if not isinstance(resources, DictionaryObject):
        return 0
    xobjects = _resolve(resources.get("/XObject"))
    if not isinstance(xobjects, DictionaryObject):
        return 0
    count = 0
    for ref in xobjects.values():
        key = id(ref) if not isinstance(ref, IndirectObject) else ref.idnum
        if key in seen:
            continue
        seen.add(key)
        xobj = _resolve(ref)
        subtype = xobj.get("/Subtype")
        if subtype == "/Image":
            count += 1
        elif subtype == "/Form":
            count += _count_xobject_images(xobj.get("/Resources"), seen)
    return count


def _image_count(page) -> int:
    try:
        return len(page.images)
    except Exception:  # malformed content stream: fall back to the resource tree
        try:
            return _count_xobject_images(page.get("/Resources"), set())
        except Exception:
            return 0


def _annotations(page) -> tuple[int, str]:
    annots = _resolve(page.get("/Annots"))
    if not isinstance(annots, ArrayObject):
        return 0, ""
    texts = []
    for ref in annots:
        annot = _resolve(ref)
        if not isinstance(annot, DictionaryObject):
            continue
        for key in ("/Contents", "/T", "/TU", "/V", "/RC"):
            value = annot.get(key)
            if value is not None and not isinstance(value, (DictionaryObject, ArrayObject)):
                texts.append(str(_resolve(value)))
    return len(annots), "\n".join(texts)


def _xmp_text(reader: PdfReader) -> tuple[bool, str]:
    try:
        meta = _resolve(reader.trailer["/Root"].get("/Metadata"))
        if meta is None:
            return False, ""
        raw = meta.get_data().decode("utf-8", errors="ignore")
    except Exception:
        return False, ""
    return True, " ".join(_XML_TAG.sub(" ", raw).split())


def _embedded_file_count(reader: PdfReader) -> int:
    try:
        names = _resolve(reader.trailer["/Root"].get("/Names"))
        if not isinstance(names, DictionaryObject):
            return 0
        tree = _resolve(names.get("/EmbeddedFiles"))
        if not isinstance(tree, DictionaryObject):
            return 0
        return _count_name_tree(tree)
    except Exception:
        return 0


def _count_name_tree(node) -> int:
    node = _resolve(node)
    count = len(_resolve(node.get("/Names", ArrayObject()))) // 2
    for kid in _resolve(node.get("/Kids", ArrayObject())):
        count += _count_name_tree(kid)
    return count


def inspect(path: Path) -> PdfReport:
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            ok = reader.decrypt("")  # many PDFs are encrypted only to restrict permissions
        except Exception:
            ok = 0
        if not ok:
            return PdfReport(backend="pypdf", encrypted=True)

    pages = []
    for number, page in enumerate(reader.pages, 1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        annot_count, annot_text = _annotations(page)
        pages.append(
            PageInfo(
                number=number,
                text=text,
                image_count=_image_count(page),
                annotation_count=annot_count,
                annotation_text=annot_text,
            )
        )

    info = reader.metadata or {}
    metadata_values = [str(v) for k, v in info.items() if v and k not in _TECHNICAL_INFO_KEYS]
    has_xmp, xmp_text = _xmp_text(reader)
    if xmp_text:
        metadata_values.append(xmp_text)

    fields = {}
    with contextlib.suppress(Exception):
        fields = reader.get_fields() or {}
    form_parts = []
    for name, fld in fields.items():
        form_parts.append(str(name))
        value = fld.get("/V") if isinstance(fld, dict) else None
        if value is not None:
            form_parts.append(str(value))

    return PdfReport(
        backend="pypdf",
        pages=pages,
        metadata_text="\n".join(metadata_values),
        has_xmp=has_xmp,
        form_field_count=len(fields),
        form_text="\n".join(form_parts),
        embedded_file_count=_embedded_file_count(reader),
    )
