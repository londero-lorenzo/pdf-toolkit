# 0002: fontTools in pdf-core, font analysis in a separate pdf-fonts package

Status: accepted.

## Context

Running on real documents, pypdf printed "fontTools is required to fully parse the encoding of a
CFF Type1 font ... but is not installed". The `ABCDEF+` prefix in the font name is a random subset
tag: the font is already embedded in the PDF, so there is nothing to download per font. What was
missing is the fontTools library, which pypdf uses to read the encoding stored inside a CFF
(Type1C) font program when the PDF has no `/ToUnicode` map. Without it that text is extracted as
control characters, so `verify` could miss a leftover term (PDFium, the second extractor, is only
a development dependency).

Other fonts cannot be decoded by any library: Type0 fonts with an Identity or embedded CMap and
Type3 fonts, both without `/ToUnicode`. For those the only safe answer is a visual check.

## Decision

- **fonttools is a dependency of pdf-core** (MIT). Extraction quality is pdf-core's job and every
  module that reads text benefits. `pdf_core.testing.make_cff_pdf` builds such a document, and a
  test shows that the text is lost without fontTools.
- **A new package, `pdf-fonts`**, holds font analysis. `scan_fonts` reports each font's kind, the
  pages using it and three issues: `cff-custom-encoding`, `no-unicode-map`, `not-embedded`.
  It is read-only today, but font work that writes PDFs (adding a missing `/ToUnicode` map, for
  example) will live there too, and `pdf-core` must never modify a PDF.
- **`pdf-toolkit fonts scan PATH...`** prints OK / NOTE / RISK per file with counts and page numbers.

## Privacy

- Results carry font kinds, issue codes, counts and page numbers, never font names: a custom
  font name can identify the organisation a document comes from.
- Files are printed as `file#N`. The paths go only to the optional `--csv` report, which is
  refused inside a protected location, like the other private outputs.

## Not done (yet)

- `verify` does not turn `no-unicode-map` into a WARN: that would change what `publish` lets
  through, so it needs its own decision.
- pypdfium2 stays a development dependency / `pdf-core[pdfium]` extra.
