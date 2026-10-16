# Migration guide: new pdf-toolkit, new Stirling, new engine

What happens to your sessions when something underneath changes, and what to do so that nothing is
redacted twice by hand or published unchecked. Three kinds of change:

1. [a new version of pdf-toolkit](#1-updating-pdf-toolkit);
2. [a new (or older) version of Stirling-PDF](#2-changing-the-stirling-pdf-version);
3. [a different redaction engine](#3-switching-to-another-engine), for example a local one that
   does not need Stirling (see [decision 0003](decisions/0003-local-redaction-engine.md)).

All three end with the same [checks](#4-checks-after-any-migration). Try every migration on
synthetic documents first (`scripts/make_demo_folder.py`), never on a real folder.

## What a session keeps

Every session has a private workspace. These files decide what the next run redoes and what
`publish` lets through:

| File | Holds | Written by |
|---|---|---|
| `manifest.json` | size and SHA-256 of each original | every `run` |
| `ledger.csv` | per file: redacted name, original hash, rules fingerprint, engine `name/version`, hash of the output the run wrote (`output_sha256`), whether it was built on a manual edit | every `run` |
| `rulesets.json` | digests of the rules each engine applied, per rules fingerprint | every `run` |
| `manual.json`, `manual/` | manual edits captured from `redacted/` | `run`, `reset-manual` |
| `review.json` | the files you reviewed, each with the hash of the file you looked at | `review`, *Mark reviewed* |

A file is redone by the next `run` when its original, the rules, or the engine `name/version`
changed, or when it was edited by hand since the last run. Otherwise it is kept as it is and only
verified again.

## 1. Updating pdf-toolkit

```
git pull
uv sync
uv run pytest -q
```

Then, for each session you are still working on, **run it once before you draw any new box**:

```
uv run pdf-toolkit redact run SESSION
```

Why: a newer version may record more about each file. Sessions run before manual edits were kept
(decision 0002) have no `output_sha256` and no `rulesets.json`, so an edit saved *before* that first
run cannot be told apart from the engine's output: the run records the file as it is, and the boxes
are lost the next time the file is redone. After one run both are recorded, and edits from then on
are kept. If you already drew boxes on a
session started with an older version, check those files after the next run and draw again what is
missing. `review.json` files from versions that did not store hashes are ignored: review those files
again.

If a version changes the format of the workspace in a way a run cannot fix, its release notes say
so.

## 2. Changing the Stirling-PDF version

Follow the **upgrade checklist** in [stirling-notes.md](stirling-notes.md#upgrade-checklist): back up
`configs/` first, change the tag, check `redact stirling-status`, run a synthetic session, then
`redact run SESSION --force` on real sessions. The engine `name/version` does not change with
Stirling's version, so without `--force` already redacted files are kept as they are.

### Rolling back to 2.14.3 (no usage limit)

Stirling 3.x meters the API: 1,000 units a month, about 2 per PDF. When they are used up, every PDF
ends with `ERR ...: HTTP 402` and nothing can be published until the next month. 2.14.3 is the last
release without metering. It is a stopgap (an old release, without fixes), not the long-term answer:
see [decision 0003](decisions/0003-local-redaction-engine.md).

1. Stop the container: `docker compose down` in the folder of your compose file.
2. Version 3.x migrated the database in `configs/`, and 2.14.3 cannot read it:
   - with the backup taken before upgrading to 3.x: move the current `configs/` aside and restore
     the backup;
   - without it: move the current `configs/` aside, start with an empty one, sign in, create a new
     API key and write it to the file named by `api_key_file` (`uv run pdf-toolkit config edit`).
3. Set `image: stirlingtools/stirling-pdf:2.14.3-fat` in the compose file, then `docker compose up -d`.
4. `uv run pdf-toolkit redact stirling-status`: it prints the version.
5. Run the synthetic session. The regex notes in `stirling-notes.md` were measured on 3.1.0: a rule
   that 2.14.3 ignores shows up as `FAIL ... term/alias ...`. Do not touch real folders until the
   synthetic session ends OK.
6. `uv run pdf-toolkit redact run SESSION --force` on each real session, then the
   [checks](#4-checks-after-any-migration).

Rolling forward again is the normal upgrade checklist, starting from the `configs/` you kept aside.

## 3. Switching to another engine

Engines are chosen in the configuration, in priority order: the first engine that handles a file
type wins.

```toml
[redaction]
engines = ["stirling", "text"]      # today: Stirling for PDF, the built-in text engine for CSV/TXT/MD

[engines.stirling]
url = "http://127.0.0.1:8080"
```

A new engine is installed as a package and gets its own `[engines.<name>]` table. Engines under a
copyleft licence (for example one based on PyMuPDF, AGPL) are never part of this repository: they
are separate packages that you install yourself (see [licensing.md](licensing.md)). Note that
`uv sync` removes packages that are not in the lock file, so after each `uv sync` check that the
engine is still installed; the engine's own instructions say how to install it so that it stays.

What happens on the first `run` after the switch:

- **Every file is redone**, without `--force`: the engine `name/version` in the ledger no longer
  matches. With a local engine the run prints `remote engine calls: 0`.
- **Manual edits** are kept only if the new engine implements `rule_digests` on the same rules as
  the old one (see the requirements in decision 0003). Otherwise the line says
  `[manual edits dropped: rules removed]` or `[manual edits dropped: engine cannot rebuild on top of it]`.
  The edits stay in `manual/`, so you can see where the boxes were and draw them again.
- **Review marks** no longer apply to rebuilt files: they hold the hash of the file you looked at.
  Review the WARN files again.
- **Publish** holds back files that changed and were not reviewed, as usual.

### Boxes drawn by hand without Stirling

Today boxes are drawn in Stirling's manual redaction (its web UI is not metered). With another tool,
make sure it **removes** what is under the box instead of covering it, then check every box: try to
select or copy the text under it, and look at the images. The checks of pdf-toolkit read text against
the rules: they cannot tell whether a logo or a header under your box was removed. The internal
editor planned in #12 is meant to remove that dependency.

### Going back

Put the old list back in `[redaction] engines` and run: the engine `name/version` changes again, so
every file is redone with the old engine. Manual edits follow the same rule as above.

## 4. Checks after any migration

1. A synthetic session (`uv run python scripts/make_demo_folder.py <empty folder>`, then
   `redact new` on that folder and `run`) ends with every file OK or with the expected WARN.
2. `uv run pdf-toolkit redact verify SESSION` on each real session: no FAIL.
3. Lines with `[manual edits dropped: ...]`: open those files and draw again what is missing.
4. WARN files: look at them and `review` them again.
5. `publish`.

If any step fails, go back (rollback above) before publishing anything.
