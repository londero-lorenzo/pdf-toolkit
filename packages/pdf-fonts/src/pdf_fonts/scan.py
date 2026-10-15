"""Which fonts a PDF uses and which of them make text extraction unreliable.

Text extraction turns character codes into Unicode through, in order: the font's /ToUnicode map,
its /Encoding, and the encoding built into the embedded font program. Issues found here:

- ``cff-custom-encoding``: a CFF (Type1C) font without /ToUnicode whose font program carries its
  own encoding. pypdf decodes it only when fontTools is installed;
- ``no-unicode-map``: a Type0 font with an Identity or embedded CMap, or a Type3 font, without
  /ToUnicode. No library can recover the text reliably: check the pages visually;
- ``not-embedded``: a font other than the standard 14 that is not embedded (informative).
"""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from io import BytesIO
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, StreamObject

STANDARD_14 = {
    "Times-Roman",
    "Times-Bold",
    "Times-Italic",
    "Times-BoldItalic",
    "Helvetica",
    "Helvetica-Bold",
    "Helvetica-Oblique",
    "Helvetica-BoldOblique",
    "Courier",
    "Courier-Bold",
    "Courier-Oblique",
    "Courier-BoldOblique",
    "Symbol",
    "ZapfDingbats",
}
FONT_FILES = ("/FontFile", "/FontFile2", "/FontFile3")


class FontKind(StrEnum):
    STANDARD14 = "standard14"
    TYPE1 = "type1"
    TYPE1C = "type1c"  # CFF
    TRUETYPE = "truetype"
    TYPE0 = "type0"
    TYPE3 = "type3"
    OTHER = "other"


class FontIssue(StrEnum):
    CFF_CUSTOM_ENCODING = "cff-custom-encoding"
    NO_UNICODE_MAP = "no-unicode-map"
    NOT_EMBEDDED = "not-embedded"


@dataclass(frozen=True)
class FontEntry:
    kind: FontKind
    issues: frozenset[FontIssue]
    pages: tuple[int, ...]  # 1-based pages that use the font


@dataclass
class FontReport:
    fonts: list[FontEntry] = field(default_factory=list)
    encrypted: bool = False
    error: str = ""  # exception type name when the file cannot be read, never its message

    def with_issue(self, issue: FontIssue) -> list[FontEntry]:
        return [f for f in self.fonts if issue in f.issues]

    def pages_with(self, issue: FontIssue) -> list[int]:
        return sorted({p for f in self.with_issue(issue) for p in f.pages})

    def kind_counts(self) -> dict[FontKind, int]:
        return {k: sum(1 for f in self.fonts if f.kind is k) for k in FontKind}


def fonttools_available() -> bool:
    return importlib.util.find_spec("fontTools") is not None


def scan_fonts(path: str | Path) -> FontReport:
    report = FontReport()
    try:
        reader = PdfReader(Path(path))
        if reader.is_encrypted:
            report.encrypted = True
            return report
        fonts: dict[object, DictionaryObject] = {}
        pages: dict[object, set[int]] = {}
        for number, page in enumerate(reader.pages, 1):
            for key, font in _page_fonts(page):
                fonts.setdefault(key, font)
                pages.setdefault(key, set()).add(number)
        cff_cache: dict[object, bool] = {}
        for key, font in fonts.items():
            kind, issues = _classify(font, cff_cache)
            report.fonts.append(FontEntry(kind, frozenset(issues), tuple(sorted(pages[key]))))
    except Exception as exc:
        report.fonts = []
        report.error = type(exc).__name__
    return report


def _get(container: Any, key: str) -> Any:
    """``container[key]`` resolved, or None (pypdf's ``.get`` does not resolve indirect objects)."""
    if not isinstance(container, DictionaryObject) or key not in container:
        return None
    return container[key]


def _key(container: DictionaryObject, name: Any) -> object:
    """Identity of an object stored in ``container``: its object number when indirect."""
    raw = container.raw_get(name)
    return (raw.idnum, raw.generation) if isinstance(raw, IndirectObject) else id(raw)


def _page_fonts(page: DictionaryObject) -> Iterator[tuple[object, DictionaryObject]]:
    seen: set[object] = set()
    yield from _resource_fonts(_get(page, "/Resources"), seen)
    annots = _get(page, "/Annots")
    for annot in annots if isinstance(annots, ArrayObject) else []:
        appearances = _get(annot.get_object(), "/AP")
        for state in ("/N", "/R", "/D"):
            entry = _get(appearances, state)
            if isinstance(entry, StreamObject):
                yield from _resource_fonts(_get(entry, "/Resources"), seen)
            elif isinstance(entry, DictionaryObject):  # one appearance per state (checkbox on/off)
                for name in entry:
                    stream = _get(entry, name)
                    if isinstance(stream, StreamObject):
                        yield from _resource_fonts(_get(stream, "/Resources"), seen)


def _resource_fonts(resources: Any, seen: set[object]) -> Iterator[tuple[object, DictionaryObject]]:
    if not isinstance(resources, DictionaryObject) or id(resources) in seen:
        return
    seen.add(id(resources))
    font_dict = _get(resources, "/Font")
    if isinstance(font_dict, DictionaryObject):
        for name in font_dict:
            font = _get(font_dict, name)
            if isinstance(font, DictionaryObject):
                yield _key(font_dict, name), font
    xobjects = _get(resources, "/XObject")
    if isinstance(xobjects, DictionaryObject):
        for name in xobjects:
            xobject = _get(xobjects, name)
            if isinstance(xobject, StreamObject) and _get(xobject, "/Subtype") == "/Form":
                yield from _resource_fonts(_get(xobject, "/Resources"), seen)


def _embedded(descriptor: Any) -> bool:
    return isinstance(descriptor, DictionaryObject) and any(name in descriptor for name in FONT_FILES)


def _base_name(font: DictionaryObject) -> str:
    name = str(_get(font, "/BaseFont") or "")[1:]
    return name[7:] if len(name) > 7 and name[6] == "+" else name  # drop the subset tag (ABCDEF+)


def _classify(font: DictionaryObject, cff_cache: dict[object, bool]) -> tuple[FontKind, set[FontIssue]]:
    subtype = _get(font, "/Subtype")
    has_unicode_map = "/ToUnicode" in font
    issues: set[FontIssue] = set()

    if subtype == "/Type3":
        if not has_unicode_map:
            issues.add(FontIssue.NO_UNICODE_MAP)
        return FontKind.TYPE3, issues

    if subtype == "/Type0":
        descendants = _get(font, "/DescendantFonts")
        cid_font = descendants[0].get_object() if isinstance(descendants, ArrayObject) and descendants else None
        if not _embedded(_get(cid_font, "/FontDescriptor")):
            issues.add(FontIssue.NOT_EMBEDDED)
        encoding = _get(font, "/Encoding")
        opaque = isinstance(encoding, StreamObject) or str(encoding).startswith("/Identity")
        if opaque and not has_unicode_map:
            issues.add(FontIssue.NO_UNICODE_MAP)
        return FontKind.TYPE0, issues

    descriptor = _get(font, "/FontDescriptor")
    if subtype == "/TrueType":
        kind = FontKind.TRUETYPE
    elif subtype in ("/Type1", "/MMType1"):
        if not _embedded(descriptor) and _base_name(font) in STANDARD_14:
            return FontKind.STANDARD14, issues
        kind = FontKind.TYPE1C if _get(descriptor, "/FontFile3") is not None else FontKind.TYPE1
    else:
        return FontKind.OTHER, issues

    if not _embedded(descriptor):
        issues.add(FontIssue.NOT_EMBEDDED)
    if kind is FontKind.TYPE1C and not has_unicode_map:
        key = _key(descriptor, "/FontFile3")
        if key not in cff_cache:
            cff_cache[key] = _cff_custom_encoding(_get(descriptor, "/FontFile3"))
        if cff_cache[key]:
            issues.add(FontIssue.CFF_CUSTOM_ENCODING)
    return kind, issues


def _cff_custom_encoding(font_file: Any) -> bool:
    """True if the CFF program has its own encoding (or cannot be parsed: assume it has)."""
    if not isinstance(font_file, StreamObject) or _get(font_file, "/Subtype") != "/Type1C":
        return False  # /OpenType programs are decoded through their cmap table
    try:
        from fontTools.cffLib import CFFFontSet

        cff = CFFFontSet()
        cff.decompile(BytesIO(font_file.get_data()), None)
        return not isinstance(cff.topDictIndex[0].Encoding, str)  # "StandardEncoding" / "ExpertEncoding"
    except Exception:
        return True
