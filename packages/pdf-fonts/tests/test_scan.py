from pdf_fonts import FontIssue, FontKind, fonttools_available, scan_fonts

from pdf_core.testing import make_cff_pdf, make_pdf, stream, write_pdf


class Doc:
    """Minimal PDF builder: pages with the given resources, objects added on demand."""

    def __init__(self):
        self.objects = [b"", b""]  # catalog and page tree, filled by write()
        self.pages = []

    def add(self, obj: bytes) -> bytes:
        self.objects.append(obj)
        return f"{len(self.objects)} 0 R".encode()

    def page(self, resources: bytes, extra: bytes = b"") -> None:
        content = self.add(stream(b"", b""))
        self.pages.append(
            self.add(
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << "
                + resources
                + b" >> /Contents "
                + content
                + extra
                + b" >>"
            )
        )

    def write(self, path):
        self.objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
        self.objects[1] = b"<< /Type /Pages /Kids [" + b" ".join(self.pages) + b"] /Count %d >>" % len(self.pages)
        return write_pdf(path, self.objects)


def type0_font(doc: Doc, *, to_unicode: bool = False) -> bytes:
    descriptor = doc.add(
        b"<< /Type /FontDescriptor /FontName /SYNTH+CidSans /Flags 4 /FontBBox [0 0 500 700] /ItalicAngle 0"
        b" /Ascent 700 /Descent 0 /CapHeight 700 /StemV 80 /FontFile2 " + doc.add(stream(b"", b"\0" * 16)) + b" >>"
    )
    cid_font = doc.add(
        b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /SYNTH+CidSans /CIDSystemInfo"
        b" << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> /FontDescriptor " + descriptor + b" >>"
    )
    cmap = b" /ToUnicode " + doc.add(stream(b"", b"")) if to_unicode else b""
    return doc.add(
        b"<< /Type /Font /Subtype /Type0 /BaseFont /SYNTH+CidSans /Encoding /Identity-H /DescendantFonts ["
        + cid_font
        + b"]"
        + cmap
        + b" >>"
    )


def test_standard_font_has_no_issue(tmp_path):
    report = scan_fonts(make_pdf(tmp_path / "a.pdf", [["one"], ["two"]]))
    assert not report.error
    [font] = report.fonts
    assert font.kind is FontKind.STANDARD14
    assert font.issues == frozenset()
    assert font.pages == (1, 2)


def test_cff_font_with_its_own_encoding(tmp_path):
    report = scan_fonts(make_cff_pdf(tmp_path / "a.pdf", ["Jane Example"]))
    [font] = report.fonts
    assert font.kind is FontKind.TYPE1C
    assert font.issues == {FontIssue.CFF_CUSTOM_ENCODING}
    assert report.pages_with(FontIssue.CFF_CUSTOM_ENCODING) == [1]


def test_cff_font_with_standard_encoding_needs_nothing(tmp_path):
    report = scan_fonts(make_cff_pdf(tmp_path / "a.pdf", ["Jane Example"], standard_encoding=True))
    [font] = report.fonts
    assert font.kind is FontKind.TYPE1C
    assert font.issues == frozenset()


def test_type0_identity_without_unicode_map(tmp_path):
    doc = Doc()
    doc.page(b"/Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >>")
    doc.page(b"/Font << /F2 " + type0_font(doc) + b" /F3 " + type0_font(doc, to_unicode=True) + b" >>")
    report = scan_fonts(doc.write(tmp_path / "a.pdf"))
    assert report.kind_counts()[FontKind.TYPE0] == 2
    assert report.pages_with(FontIssue.NO_UNICODE_MAP) == [2]
    assert len(report.with_issue(FontIssue.NO_UNICODE_MAP)) == 1
    assert not report.with_issue(FontIssue.NOT_EMBEDDED)


def test_type3_without_unicode_map(tmp_path):
    doc = Doc()
    font = doc.add(
        b"<< /Type /Font /Subtype /Type3 /FontBBox [0 0 1 1] /FontMatrix [1 0 0 1 0 0] /CharProcs << >>"
        b" /Encoding << /Differences [] >> /FirstChar 0 /LastChar 0 /Widths [0] >>"
    )
    doc.page(b"/Font << /F1 " + font + b" >>")
    [entry] = scan_fonts(doc.write(tmp_path / "a.pdf")).fonts
    assert entry.kind is FontKind.TYPE3
    assert entry.issues == {FontIssue.NO_UNICODE_MAP}


def test_fonts_in_form_xobjects_and_annotations_are_found_once(tmp_path):
    doc = Doc()
    font = doc.add(b"<< /Type /Font /Subtype /TrueType /BaseFont /SYNTH+Sans >>")  # not embedded
    form = doc.add(
        stream(b"/Type /XObject /Subtype /Form /BBox [0 0 10 10] /Resources << /Font << /F9 " + font + b" >> >>", b"")
    )
    doc.page(b"/XObject << /Fm1 " + form + b" >>")
    appearance = doc.add(
        stream(b"/Subtype /Form /BBox [0 0 10 10] /Resources << /Font << /F8 " + font + b" >> >>", b"")
    )
    annot = doc.add(b"<< /Type /Annot /Subtype /FreeText /Rect [0 0 10 10] /AP << /N " + appearance + b" >> >>")
    doc.page(b"", b" /Annots [" + annot + b"]")
    [entry] = scan_fonts(doc.write(tmp_path / "a.pdf")).fonts
    assert entry.kind is FontKind.TRUETYPE
    assert entry.issues == {FontIssue.NOT_EMBEDDED}
    assert entry.pages == (1, 2)


def test_unreadable_file_reports_the_error_type_only(tmp_path):
    path = tmp_path / "Jane Example.pdf"
    path.write_bytes(b"not a pdf")
    report = scan_fonts(path)
    assert report.error and "Jane" not in report.error
    assert report.fonts == []


def test_fonttools_is_installed():
    assert fonttools_available()
