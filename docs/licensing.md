# Licensing

pdf-toolkit is released under the [Apache License 2.0](../LICENSE); see also [NOTICE](../NOTICE).
Versions published before [decision 0005](decisions/0005-apache-2.0-licence.md) were under MIT,
and whoever received them keeps those rights.

## Dependency policy

`pdf-core`, `pdf-fonts`, `pdf-redaction` and `pdf-toolkit` accept permissive dependencies (MIT, BSD,
Apache-2.0, PSF, ISC, MPL-2.0). `scripts/check_licenses.py` runs in CI and fails on any GPL, LGPL or
AGPL distribution in the environment, except the LGPL ones it lists by name (see below).

| Dependency | Licence | Used by |
|---|---|---|
| pypdf | BSD-3-Clause | pdf-core (default backend) |
| fontTools | MIT | pdf-core (decodes embedded CFF fonts for pypdf), pdf-fonts |
| pypdfium2 / PDFium | Apache-2.0 or BSD-3-Clause / BSD-3-Clause | pdf-core `[pdfium]` extra |
| tkinter (Python stdlib) | PSF | GUI |

Stirling-PDF is **not** a dependency: it is a separate program run by the user and reached over
HTTP on localhost. Its core is MIT, while parts of it are under a proprietary licence; check its
[LICENSE](https://github.com/Stirling-Tools/Stirling-PDF/blob/main/LICENSE) for your own use.

## LGPL libraries

An LGPL library is allowed when it is used unmodified, installed as a separate package and loaded
dynamically, so that the user can replace it. Each one is added by name to
`scripts/check_licenses.py`, with the reason, in the change that introduces it. A frozen build keeps
it as separate, replaceable files and ships its licence text. None is used yet; PySide6 (#4) is the
first expected.

## Copyleft components

GPL and AGPL libraries (for example PyMuPDF, AGPL-3.0) may only be used from **separate, optional
packages** that register an engine or a module through the entry points
(`pdf_toolkit.redaction_engines`, `pdf_toolkit.modules`). Such packages carry their own licence and
are not part of this repository's code.

## What stays in this repository

What is needed to redact correctly and to check the result (engines, true removal of content,
`verify`, the gates of `publish`) is part of this repository, not of an optional package. See
[decision 0005](decisions/0005-apache-2.0-licence.md).

## Contributions

Contributions are accepted under the Apache License 2.0 (inbound = outbound, section 5 of the
licence): by opening a pull request you agree that your contribution is licensed under the same
terms as the project. No CLA is needed and you keep your copyright. Apache-2.0 allows anyone to
use the code in their own projects, provided the licence, the copyright notices and `NOTICE` are
kept and changed files are marked.
