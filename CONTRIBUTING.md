# Contributing

Thanks for helping! A few rules matter more than usual here, because this project handles
personal data.

1. **Never share real documents.** Not in issues, not in pull requests, not in test fixtures.
   Reproduce problems with `pdf_core.testing.make_pdf` and invented values. If a bug only shows on a
   real file, describe its *structure* (number of pages, scanned or not, fonts, producer) instead.
2. **Keep output safe.** New messages must never contain matched values, terms or original names.
3. **Network.** No new networking code outside `engines/stirling.py`.
4. **Licences.** Permissive dependencies only; `uv run python scripts/check_licenses.py` must pass.
5. **Tests.** `uv run pytest` and `uv run ruff check .` must pass; add tests for new rules and engines.
6. **Commits.** Conventional commits, in English.

## Adding a PII pattern pack

Add a list to `_PACKS` in `packages/pdf-redaction/src/pdf_redaction/rules/patterns.py` with
`STRONG` patterns for identifiers that are almost never false positives and `WEAK` ones for the
rest. Patterns must compile in Python and Java (no named groups, no possessive quantifiers).
Add tests with invented values.

## Adding an engine or a module

Create a separate package that declares an entry point in `pdf_toolkit.redaction_engines`
(an object with `name`, `version`, `suffixes`, `redact(src, dst, ctx)`) or in
`pdf_toolkit.modules` (a `ToolkitModule`). See `docs/architecture.md`.

Contributions are licensed under MIT (see `docs/licensing.md`).
