# pdf-core

Read-only PDF inspection shared by the pdf-toolkit modules. **pdf-core never modifies a PDF**:
modules decide what to write.

```python
from pdf_core import inspect_pdf

report = inspect_pdf("document.pdf")  # default backend: pypdf
for page in report.pages:
    print(page.number, page.image_count, len(page.text))
```

Backends:

| name     | library     | install                      | notes                                   |
|----------|-------------|------------------------------|-----------------------------------------|
| `pypdf`  | pypdf (BSD) | default                      | text, images, metadata, XMP, forms      |
| `pdfium` | pypdfium2 (Apache-2.0 / BSD-3) | `pdf-core[pdfium]` | PDFium text extraction (same engine family as Chromium) |

fontTools (MIT) is a dependency: pypdf needs it to decode text written with embedded CFF (Type1C)
fonts that carry their own encoding. Without it such text comes out as control characters.

`available_backends()` lists the backends importable in the current environment. Using two
independent extractors is useful when you need to be sure that some text is *not* in a file.
