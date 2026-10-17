# 0005: Apache-2.0 licence

Status: accepted.

## Context

pdf-toolkit was published under MIT. Every commit so far has a single author, so the licence of
later versions can change without anyone else's consent. Code already published under MIT stays
available under MIT to whoever received it.

What the licence must allow:

- a public project, open to a community and to contributions without paperwork;
- separate packages plugged in through the entry points, under their own licence, so that copyleft
  engines such as PyMuPDF stay out of this repository;
- use by companies, whose legal review is part of adopting a tool.

#4 plans PySide6 (LGPL), which the dependency policy rejected; the dependency policy is reviewed
here together with the licence.

## Options considered

| | Separate packages under their own licence | Contributions | Fit |
|---|---|---|---|
| **MIT** (until now) | yes, through the entry points | same licence, by a note in `CONTRIBUTING.md` | good |
| **Apache-2.0** (chosen) | as MIT | same licence, by section 5 of the licence | good, plus a patent grant |
| **MPL-2.0** | yes | same licence | protects little for a Python project |
| **GPL-3.0 / AGPL-3.0** | GPL-compatible ones only | same licence | many companies avoid it; the code published under MIT stays MIT anyway |

## Decision

### Licence

From this change, every package of the repository (`pdf-core`, `pdf-fonts`, `pdf-redaction`,
`pdf-toolkit`) is under the **Apache License 2.0**. `LICENSE` holds the unmodified text from
apache.org; `NOTICE` holds the copyright line.

Why Apache-2.0 rather than MIT. Both are permissive, so for users nothing changes in practice.
Apache-2.0 adds two clauses that match the needs above:

- **Patents (section 3).** Every contributor grants a licence on their patents that the
  contribution uses, and loses it if they sue over patents in the work. Companies look for this
  before adopting a project.
- **Contributions (section 5).** Anything submitted for inclusion is under Apache-2.0 unless stated
  otherwise. The "inbound = outbound" rule is in the licence itself, so no CLA is needed.

Costs, accepted: redistributors keep `NOTICE` and mark the files they changed (section 4);
Apache-2.0 cannot be combined with GPL-2.0-only code, and no dependency is under it. The switch is
cheap now: one author, no licence headers in the source files.

### What stays in this repository

- Separate packages register engines or modules through the entry points
  (`pdf_toolkit.redaction_engines`, `pdf_toolkit.modules`) under their own licence. The core needs
  no change for them.
- **What is needed to redact correctly and to check the result is part of this repository**: the
  engines, true removal of content (rules and areas), `verify`, and the gates of `publish`. A tool
  that people trust with personal data does not depend on an optional package for its safety.

### Contributions

Contributions are accepted under Apache-2.0 (section 5), without a CLA. Contributors keep their
copyright.

### Dependencies

- Permissive licences (MIT, BSD, Apache-2.0, PSF, ISC, MPL-2.0) are accepted, as before.
- **GPL and AGPL** libraries (for example PyMuPDF) only in separate optional packages, as before.
- **LGPL** libraries are allowed when they are used unmodified, installed as separate packages and
  loaded dynamically, so that the user can replace them. Each one is listed by name in
  `scripts/check_licenses.py`, with the reason, when it is added; any other LGPL distribution still
  fails the check. A frozen build keeps them as separate, replaceable files and ships their licence
  text. The first expected entry is PySide6 for #4: this settles the point left open in 0004.

## Follow-up

- `LICENSE`, `NOTICE`, the `license` field of each `pyproject.toml`, `README.md`,
  `CONTRIBUTING.md`, `CLAUDE.md`, `docs/licensing.md` and `scripts/check_licenses.py` updated with
  this record.
- The LGPL allowlist in `scripts/check_licenses.py` is added with #4.
- This record is not legal advice.
