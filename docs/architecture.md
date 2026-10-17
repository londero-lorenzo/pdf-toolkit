# Architecture

```
apps/pdf-toolkit  (pdf_toolkit)        CLI, tkinter GUI, configuration, module registry
        │ entry point "pdf_toolkit.modules"  →  redaction, fonts (built in), future: pdf2md, translate
        ▼
packages/pdf-redaction (pdf_redaction)  rules · names · engines · verify · session · pipeline · publish · audit
        │ entry point "pdf_toolkit.redaction_engines"  →  stirling (PDF), text (CSV/TXT/MD)
        ▼
packages/pdf-fonts (pdf_fonts)          font analysis: kinds, Unicode maps, embedding. Read-only today;
        │                               font work that writes PDFs goes here, never in pdf-core
        ▼
packages/pdf-core (pdf_core)            read-only inspection: text per page, images, annotations,
                                        forms, attachments, metadata/XMP; backends pypdf | pdfium
```

Principles:

- **pdf-core reads and understands PDFs; it never modifies them.** Modules decide what to write.
- **Library first.** All behaviour lives in `pdf-redaction`; CLI and GUI are thin layers over
  `pdf_toolkit.redaction_service`.
- **Pluggable.** Engines and modules are discovered through entry points, so separate packages,
  under any licence, can add a PDF engine (e.g. a PyMuPDF one) or a whole module without forking.
- **Deterministic.** Same originals + same context → same names and same skip decisions.

## Redaction flow

```
source (read only) ──copy──► workspace/originals ──SafePathMapper──► redacted names
                                     │
                                     ├─ .pdf  → StirlingEngine: auto-redact → sanitize
                                     ├─ .csv/.tsv/.txt/.md → TextEngine
                                     └─ other → skipped (never published)
                                     ▼
                              workspace/redacted ──verify (pypdf + PDFium)──► OK / WARN / FAIL
                                     │                                      ledger.csv
                                     ▼  publish: re-verify, reviewed WARN only
                              destination folder    (+ _text/*.txt extracts, .published.json)
                              (--to FOLDER, remembered per session; default output_root/<alias>)
```

A redacted file edited by hand after a run (its SHA-256 no longer matches `ledger.csv`) is copied
to `workspace/manual/` by the next run and becomes the engine's input for that file instead of the
original, as long as rules were only added (`pdf_redaction.manual`, decision
[0003](decisions/0003-manual-redactions.md)). Engines opt in with `rule_digests(ctx)`.

## Rules

`RedactionContext` merges global term/alias files, the folder's `.redaction/` files and the PII
pattern packs (`common`, `it`; add yours in `rules/patterns.py`). Patterns must be valid in both
Python and Java because the same rules are sent to Stirling (`rules/java_regex.py`).

Term rules (`rules/terms.py`):

- names of 2–3 words match in any order and with flexible whitespace;
- codes (one token, at least 8 alphanumerics with a digit) tolerate separators between characters;
- for file names, code rules also match when glued to other characters.
