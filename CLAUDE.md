# pdf-toolkit: rules for AI assistants and contributors

Public Apache-2.0 repository. Language: **English** for code, comments, docs, commit messages.

## Data
- **Synthetic data only.** Tests and examples build their own documents with
  `pdf_core.testing.make_pdf` and invented values (see `packages/pdf-redaction/tests/redaction_fixtures.py`).
  Never add real documents, real names, real codes, real paths or screenshots of real files.
- Never read the user's configuration (`%APPDATA%/pdf-toolkit/`, `~/.config/pdf-toolkit/`), any
  `.redaction/` folder or any workspace: they contain private data (denied in `.claude/settings.json`).
- When running the app on a user's real data, only the user runs it; you see the console output,
  which by design contains no private values.

## Code
- Never print, log or put in an exception message a matched value, a redaction term or an original
  file name. Report rule labels, counts and redacted paths (`pdf_toolkit/safety.py`).
- Networking code is allowed only in `packages/pdf-redaction/src/pdf_redaction/engines/stirling.py`,
  and only towards loopback addresses (`tests/test_network_boundary.py` enforces it).
- `pdf-core` never modifies a PDF.
- Dependencies: permissive licences only (`scripts/check_licenses.py`); LGPL only when listed by
  name there (`docs/decisions/0004-apache-2.0-licence.md`). GPL and AGPL libraries go in
  separate optional packages that use the entry points.
- Regexes in `rules/` must work in both Python and Java (they are sent to Stirling-PDF).

## Workflow
- `uv sync`, `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`.
- Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`), small and focused.
- Before pushing: `uv run pdf-toolkit redact audit-repo .` must report no FAIL (run by the user,
  with their own context).
