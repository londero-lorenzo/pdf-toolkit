# pdf-toolkit

A modular, local-first PDF toolkit (CLI + desktop GUI). Its first module is **folder redaction**:
prepare a whole folder of documents for sharing (with a colleague, a public repository, an AI
assistant...) without leaking personal data.

> Status: early alpha. Interfaces may change. Feedback and pull requests are welcome.

## What the redaction module does

1. **Opens a source folder read-only** and copies it into a private *workspace*.
2. Applies a **per-folder redaction context** (`<folder>/.redaction/`): terms to hide, aliases
   (`real value -> pseudonym`), PII pattern packs, CSV columns to drop, merged with your global lists.
3. **Redacts contents and names**:
   - PDFs through a local [Stirling-PDF](https://github.com/Stirling-Tools/Stirling-PDF) (real text
     removal, then sanitising of metadata, attachments, scripts and links);
   - CSV/TSV (cell by cell), TXT and Markdown in Python;
   - every file and folder name (terms, aliases, PII, long digit codes; dates such as `2025-12` are kept).
4. **Verifies** every output with two independent PDF text extractors (pypdf and PDFium), plus
   metadata, annotations, form fields and attachments. Results: `OK`, `WARN` (needs a human look:
   images, scans, weak hits) or `FAIL`.
5. **Publishes** to an output folder only files that are OK, or WARN and marked as reviewed.

It never prints a matched value or an original file name, so its output is safe to paste or to
show to an assistant. See [docs/privacy-model.md](docs/privacy-model.md).

## Repository layout

```
packages/pdf-core        read-only PDF inspection (pypdf, optional PDFium backend)
packages/pdf-redaction   redaction library: rules, names, engines, verification, sessions, publishing
apps/pdf-toolkit         the app: configuration, CLI, tkinter GUI, module registry
docker/stirling          docker compose template for the local Stirling-PDF engine
docs/                    architecture, privacy model, Stirling notes, licensing
```

More modules (PDF to Markdown, translation) will plug into the same shell through the
`pdf_toolkit.modules` entry point.

## Quick start (Windows, macOS, Linux)

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), Docker (for PDFs).

```bash
git clone https://github.com/<owner>/pdf-toolkit && cd pdf-toolkit
uv sync

# 1. local PDF engine (copy docker/stirling/docker-compose.yml to a private folder first)
docker compose up -d                       # then create an API key in Stirling's account settings
# 2. configuration (outside the repository)
uv run pdf-toolkit config init             # writes %APPDATA%/pdf-toolkit/config.toml (or ~/.config/...)
uv run pdf-toolkit config edit             # set workspace_root, output_root, api_key_file...
uv run pdf-toolkit config check
uv run pdf-toolkit redact stirling-status
```

### GUI

```bash
uv run pdf-toolkit gui
```

*New session from folder* → *Folder context* → *Preview names* → *Redact + verify* → open and
review WARN files → *Publish*.

### CLI

```bash
uv run pdf-toolkit redact context  "D:/originals/2025"  --init   # creates .redaction/ in the folder
uv run pdf-toolkit redact new      "D:/originals/2025"  invoices-2025
uv run pdf-toolkit redact preview-names invoices-2025            # private CSV in the workspace
uv run pdf-toolkit redact run      invoices-2025                 # incremental; --force to redo
uv run pdf-toolkit redact review   invoices-2025  "scan.pdf"     # after a visual check
uv run pdf-toolkit redact publish  invoices-2025
uv run pdf-toolkit redact audit-repo .  --source "D:/originals/2025"   # before git push
```

Exit codes: `0` all OK, `2` something needs review, `1` failure.

## Development

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run python scripts/check_licenses.py
```

Tests generate their own synthetic PDFs and data (`pdf_core.testing.make_pdf`): **never add real
documents to the repository.** See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE). Dependencies are permissive only (see [docs/licensing.md](docs/licensing.md)).
Stirling-PDF is a separate program you run yourself; pdf-toolkit only talks to its HTTP API.
