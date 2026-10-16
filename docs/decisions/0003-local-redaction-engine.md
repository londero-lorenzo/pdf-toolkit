# 0003: a redaction engine that does not depend on Stirling-PDF's quota

Status: proposed. The options are compared here; the choice is made after the evaluation below.

## Context

PDF redaction is done by a self-hosted Stirling-PDF on 127.0.0.1 (`engines/stirling.py`). Since
3.0, Stirling meters its API: API calls, Processor and AI share a free allowance of **1,000 units a
month**, counted by the local server even when it is not linked to stirling.com
([releases](https://github.com/Stirling-Tools/Stirling-PDF/releases),
[pricing](https://www.stirling.com/pricing),
[Heise](https://www.heise.de/en/news/10-000-PDFs-Stirling-PDF-makes-it-one-job-11466333.html)).
When the allowance is used up, every call answers `HTTP 402` (`FREE_TIER_EXHAUSTED`) until the next
month, and `run` reports an `ERR` for every PDF: nothing can be published.

pdf-toolkit spends up to two units per PDF (redaction, then `sanitize-pdf`; `EngineResult.remote_calls`),
so a month covers about 500 PDFs, re-runs and `--force` included. Using the web editor in a browser
is not metered ([Jacar](https://jacar.es/en/upgrade-stirling-pdf-3-with-docker/)).

What is not an option:

- **Linking the instance** (+500 units): `stirling-notes.md` forbids "Connect".
- **Disabling the counter**: it is in `app/proprietary` / `app/saas`, under Stirling's proprietary
  licence. Patching it or resetting its database is not something this project does or documents.

The quota is a business decision of a third party and may change again. A tool that people rely on
to publish documents should not stop working because of it.

## Options

1. **Stay on Stirling 3.x and buy a plan.** No code. Keeps a recurring cost and the dependency on
   pricing decisions, and the Docker server.
2. **Pin Stirling 2.14.3**, the last release without metering. No code, quick to apply (a fresh
   `configs/` and a new API key, or the backup taken before 3.0; see `docs/migration-guide.md`).
   Frozen on an old release: no fixes, and the regex dialect notes (measured on 3.1.0) must be
   measured again. A stopgap, not a solution.
3. **PyMuPDF engine in a separate optional package.** PyMuPDF (AGPL-3.0 or commercial licence) has
   true redaction: `add_redact_annot` + `apply_redactions` remove the text under a rectangle, with
   options for the images and drawings it touches, and `Document.scrub()` covers what `sanitize-pdf` does. It must live outside
   this repository's uv workspace (`scripts/check_licenses.py` fails on any AGPL distribution in the
   environment, CI included) and register through `pdf_toolkit.redaction_engines`.
4. **PDFium engine in `pdf-redaction`.** `pypdfium2` (Apache-2.0 / BSD-3-Clause) is already the
   `pdf-core[pdfium]` extra used by `verify`. PDFium has no ready-made redaction: the engine finds
   matches with the text page API (character boxes), removes or rewrites the page objects they belong
   to (text, images, paths), and regenerates the page content. Partial text objects (a match inside a
   longer run) are the hard part. Stirling's `auto-redact` is itself built on PDFium (JPDFium, MIT;
   see `stirling-notes.md`) and is a reference for the approach. Sanitising (JavaScript, embedded files, XMP, metadata,
   links) can be done with pypdf (BSD-3-Clause) in the same package.
5. **Hybrid: Stirling for redaction, local sanitising** (pypdf). Halves the units spent, needs
   little code, but keeps the dependency. Useful as a first step towards 4, since the sanitiser is
   the same.

## Criteria

| | 1 Plan | 2 Stirling 2.14.3 | 3 PyMuPDF package | 4 PDFium in pdf-redaction | 5 Hybrid |
|---|---|---|---|---|---|
| Monthly limit | paid | none | none | none | halved |
| Licence / packaging | external program | external program | AGPL, separate package outside the workspace and CI | permissive, in our own code | external + permissive |
| True removal of text | yes (JPDFium; silent fallback to boxes, see `stirling-notes.md`) | to measure | yes | to build | as 1/2 |
| Removal under an *area* (#15) | no: overlay only | no: overlay only | yes | to build, shared with #15 | no |
| Regex rules | Java dialect, rules dropped silently | to measure | Python `re`, matched on extracted text | Python `re`, matched on extracted text | as 1/2 |
| Sanitise equivalent | `sanitize-pdf` | `sanitize-pdf` | `scrub()` | pypdf | pypdf |
| Docker needed | yes | yes | no | no | yes |
| Effort | none | small | medium | large | small |
| Maintenance | follows weekly releases | none, but ageing | follows PyMuPDF | ours | both |

Every option matches on **extracted text**: a font without a Unicode map (#7) is neither redacted
nor found by `verify` with any of them. This is a limit to report, not a difference between options;
the editor preview (#13) and the font scan in the verdict (#7, #8) address it.

## Interplay with open issues

| Issue | 1 / 2 Stirling | 3 PyMuPDF | 4 PDFium | 5 Hybrid |
|---|---|---|---|---|
| #5 engine without Docker | not solved | solved, as a plugin | solved, in the core | not solved |
| #12 internal editor | no help | cannot be used by the editor (permissive core) | same code as the editor | no help |
| #13 page rendering | - | - | already pypdfium2 | - |
| #15 true area removal | overlay only | yes, but only inside the plugin | same page-object code | - |

The verdict cache and `redact status` (#3) do not depend on the engine.

### The internal editor weighs most

#12 has already chosen **pypdfium2** for rendering (#13) and for **true area removal at publish**
(#15), in `pdf-redaction`, with permissive dependencies only. The removal of text, image and path
objects that #15 needs is the same work a rule-based engine needs: a rule match is just an area
computed from character boxes. So:

- with **option 4**, one piece of code (page-object removal + content regeneration + per-area
  validation) serves the quota problem, #5 and #15;
- with **option 3**, the editor still needs its own PDFium removal for #15, or #15 must also go
  through a plugin, which would make true area removal unavailable to anyone without the AGPL
  package. Two removal implementations would have to be kept correct;
- **Stirling** in any version helps neither: its area endpoints only add a filled rectangle
  (`0002-manual-redactions.md`).

### A hidden dependency of 0002

Decision 0002 keeps manual edits as the base of later runs. Today those boxes are drawn in
Stirling's viewer. Leaving Stirling therefore also needs **another tool that truly removes content
under a box**, until the internal editor (#13 + #15) exists. Two orders are possible:

1. **Rules engine first.** Boxes keep being drawn in Stirling's web UI (not metered) or in another
   tool that removes content, then checked by hand as the guide already asks.
2. **Engine and editor together**, on the shared PDFium code: the removal code is written once, and
   the switch happens when both are usable.

The open point of #12 stays: does a file with areas still start from a captured external edit, or
always from the original?

### Settled elsewhere

- **#4, Qt:** #4 plans PySide6 (LGPL), which the dependency policy rejected. Settled by
  [0004](0004-apache-2.0-licence.md): LGPL libraries are allowed when used unmodified and
  loaded dynamically, each listed by name in `scripts/check_licenses.py`.

## Requirements for any new engine

From `engines/base.py` and `pipeline.py`:

- `name`, `version`, `suffixes`, `redact(src, dst, ctx)`; `version` changes whenever the output
  would change. A different `name/version` redoes every file on the next run, without `--force`
  (`pipeline.py`, `engine_id` and `Ledger.is_current`).
- **`rule_digests(ctx)` is required**, or every manual edit is dropped (`engine cannot rebuild on
  top of it`).
- **Keep manual edits across the switch.** The rules an edit has already been through are looked up
  in `rulesets.json` under the *previous* engine's name and compared with the new engine's
  `rule_digests`. Stirling digests the strings of `to_java_patterns(ctx)`; a new engine must digest
  the same strings (or a shared, engine-neutral list of effective rules that both use), otherwise
  every existing edit is dropped as `rules removed` on the first run after the switch.
- No network code: `tests/test_network_boundary.py` keeps `engines/stirling.py` as the only module
  allowed to open connections.
- Rules must keep working in Java (`CLAUDE.md`) as long as Stirling is a supported engine.
- `verify` stays independent of the engine and keeps two extractors.

## Evaluation

A spike per remaining option (3 and 4; 5 as a by-product of 4), on synthetic documents only:

- the session built by `scripts/make_demo_folder.py`, and the documents of
  `packages/pdf-redaction/tests/redaction_fixtures.py`;
- every output passes `verify` (pypdf + PDFium);
- a match inside a longer text run is removed without losing the text around it;
- text, an image and a vector logo under an area are gone, not covered; the test double that only
  draws a rectangle (as `LeakyEngine` does for text) is caught;
- JavaScript, embedded files, XMP, metadata and links are removed;
- time per PDF on a folder of synthetic multi-page files, compared with Stirling;
- installation on Windows, and how an optional package survives `uv sync`, which removes packages
  that are not in the lock file.

## Decision

Open, until the evaluation is done. Meanwhile:

- Stirling stays pinned (`docker/stirling/docker-compose.yml`) and is upgraded only with the
  checklist in `stirling-notes.md`. Option 2 is the documented way out when the allowance runs out.
- Phase 0 below makes a used-up allowance visible and cheap.

## Problems found in use and planned fixes

Reported while using the app. Causes are from reading the code; #3 and #4 were not reproduced yet.
The fixes belong before, or together with, the engine switch, since the switch redoes every file.

### Phase 0: quota errors (small, independent)

- `StirlingClient._request` has hints for 401, 403 and 413, not for 402: add one ("Stirling's
  monthly free allowance is used up").
- Stop a run at the first quota error instead of trying every remaining file.
- Troubleshooting row for `HTTP 402` in `redaction-guide.md` (done with this record).

### Manual edits seem to need "Verify again" before "Redact + verify"

"Verify again" is read-only: it cannot change what a run keeps. Likely causes:

- **First run after updating pdf-toolkit.** Ledgers written before 0002 have no `output_sha256`, so
  an edit is not recognised; the run then records the hash of the file *as it is*, edit included,
  as if the engine had written it. (A recognised edit whose rules are not in `rulesets.json` is
  dropped as `rules removed`.) From the second run on, edits are kept: it looks as if the extra step
  fixed it.
- **The table does not show a fresh edit.** The `[edited by hand: run Redact + verify to keep it]`
  marker only appears after a verify, which suggests that a verify is needed.

Fixes: a version number for the workspace files, with an explicit migration when a session is
opened (and a message saying what it did, as in the migration guide); refresh the manual state when
the window gets focus back, by size and mtime first, so a saved edit shows up without a verify.

### "Verify again" removes some "Reviewed" marks

A mark is stored as the SHA-256 of the file when it was marked (`review.json`) and counts only while
the file still has that hash. "Verify again" only re-reads the marks, so the file changed after it
was marked: a box drawn after the review, a viewer that saves on close, or a run that rebuilt the
file. Also, "Mark reviewed" is not disabled while a job runs, so a mark can be taken on a file that
is about to be rewritten, and the table shows "yes" until the next refresh.

Fixes: disable the review buttons during jobs; tie the mark to the output recorded in the ledger
and say why a mark no longer applies (`edited after review`, `rebuilt by a run`).

### Verification is repeated when nothing changed

`FileVerdict` lives only in memory. Opening a session, "Verify again", every unchanged file in a run
and `publish` all verify every file again.

Fix: store verdicts keyed by (output SHA-256, context fingerprint, redacted path, verify version,
backend versions), checked cheaply by size and mtime first. Used by opening a session, "Verify
again" and unchanged files in `run`; also by `redact status` (#3). `publish` keeps a full check:
it is the last gate.

### Slow loading

Opening a session always runs a full, sequential verify: each PDF is read with both backends, the
matchers are rebuilt for every page (`scan_text` calls `ctx.matchers()`), and the review marks are
hashed on the GUI thread (`Session.reviewed`).

Fixes, in order: the verdict cache above; matchers built once per context; hashing off the GUI
thread; a process pool for verification (pypdf is pure Python: threads gain little).

## Follow-up

- Phase 0 as a small `fix:` change.
- The evaluation spikes, then this record moves to *accepted* with the chosen option.
- The fixes above, each as its own issue.
- `docs/migration-guide.md` gets the concrete steps of the chosen engine.
