# pdf-fonts

Font analysis for PDFs. Today it only reads: which fonts a document uses and whether text written
with them can be extracted reliably. Future font work that writes PDFs (for example adding a
missing `/ToUnicode` map) goes here, because `pdf-core` never modifies a PDF.

```python
from pdf_fonts import FontIssue, scan_fonts

report = scan_fonts("document.pdf")
print(report.kind_counts())
print(report.pages_with(FontIssue.NO_UNICODE_MAP))  # pages to check visually
```

Issues:

| issue                 | meaning                                                                 | what to do                         |
|-----------------------|-------------------------------------------------------------------------|------------------------------------|
| `cff-custom-encoding` | CFF (Type1C) font without `/ToUnicode` that carries its own encoding     | nothing: decoded through fontTools |
| `no-unicode-map`      | Type0 (Identity or embedded CMap) or Type3 font without `/ToUnicode`     | check those pages visually         |
| `not-embedded`        | font other than the standard 14 that is not embedded                     | informative                        |

Results contain font kinds, issue codes, counts and page numbers, never font names or text: a
custom font name can identify the organisation a document comes from.

From the command line: `pdf-toolkit fonts scan FOLDER`.
