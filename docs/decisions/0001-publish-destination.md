# 0001: the publish destination is chosen at publish time

Status: accepted (issue #1).

## Context

`redact publish` used to write to `<output_root>/<alias>/`, with `output_root` fixed in the
configuration (`--output` only replaced the root and still appended `<alias>/`). In practice the
destination is decided when publishing and changes between sessions: a folder to send, a folder in
a repository, a temporary upload folder. A global root does not fit, and the alias sub-folder is not
always wanted.

## Decision

Options 1 and 3 of the issue, combined:

- `publish SESSION --to FOLDER` publishes **exactly** into `FOLDER` (no alias sub-folder).
- The destination is stored in the session (`session.json`, key `destination`). A later `publish`
  without `--to` reuses it; the GUI pre-fills it.
- `output_root` stays as an optional default: while a session has no destination, `publish` uses
  `<output_root>/<alias>`. Without `output_root` and without `--to`, `publish` fails with
  "no destination".
- `--output` is removed. `--to <root>/<alias>` does the same.

Why not option 2 (no `output_root` at all): a default is convenient for the common case of one
shared folder, and it keeps existing configurations working.

## Guards

Checked at publish time, on the real destination:

- it must be disjoint from the source, the workspace and `workspace_root` (when configured);
- `protected_locations` do **not** apply to destinations. They exist to keep *unredacted* data out
  of synced or shared folders; published files are verified and are meant to go to such folders.
  Workspaces are still refused inside `output_root` and inside any protected location.

## Files already in the destination

- `.published.json` now has the form `{"schema": 2, "alias": ..., "files": [...]}`. The alias is the
  owner: a folder owned by another session is refused, so two sessions can never delete each
  other's files. The old format (a bare list) is read as owned by the current session and rewritten
  on the next publish. Entries that point outside the folder are ignored.
- A publish removes only the files listed there that no longer qualify.
- Files not written by pdf-toolkit are never deleted **and never overwritten**: a file that would
  land on one is held back ("a file not written by pdf-toolkit is in the way"), and their count is
  reported (CLI note, GUI confirmation).

## Changed destination

The previous folder is left exactly as it was. The CLI and the GUI report its path and how many
files this session published there, so the user can clean it up. Paths are printed only if no part
of them matches a redaction rule; otherwise they are replaced by "(folder hidden: its path matches
a redaction rule)", in line with the `file#N` rule for redacted paths. No automatic or optional
clean-up of the old folder was added: it keeps `publish` from ever deleting outside the folder it
was just asked to write to.
