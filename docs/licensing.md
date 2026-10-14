# Licensing

pdf-toolkit is released under the [MIT licence](../LICENSE).

## Dependency policy

Only permissive dependencies are allowed in `pdf-core`, `pdf-redaction` and `pdf-toolkit`
(MIT, BSD, Apache-2.0, PSF, ISC). `scripts/check_licenses.py` runs in CI and fails on any GPL,
LGPL or AGPL distribution in the environment.

| Dependency | Licence | Used by |
|---|---|---|
| pypdf | BSD-3-Clause | pdf-core (default backend) |
| pypdfium2 / PDFium | Apache-2.0 or BSD-3-Clause / BSD-3-Clause | pdf-core `[pdfium]` extra |
| tkinter (Python stdlib) | PSF | GUI |

Stirling-PDF is **not** a dependency: it is a separate program run by the user and reached over
HTTP on localhost. Its core is MIT, while parts of it are under a proprietary licence; check its
[LICENSE](https://github.com/Stirling-Tools/Stirling-PDF/blob/main/LICENSE) for your own use.

## Copyleft components

Copyleft libraries (for example PyMuPDF, AGPL-3.0) may only be used from **separate, optional
packages** that register an engine or a module through the entry points
(`pdf_toolkit.redaction_engines`, `pdf_toolkit.modules`). Such packages carry their own licence and
are not part of this repository's MIT code.

## Extensions and contributions

Contributions are accepted under the MIT licence (inbound = outbound): by opening a pull request
you agree that your contribution is licensed under the same terms as the project. MIT allows
anyone, including the maintainers, to build closed-source products on top of the code, provided the
copyright notice is kept. The entry points above are the intended way to add proprietary modules.
