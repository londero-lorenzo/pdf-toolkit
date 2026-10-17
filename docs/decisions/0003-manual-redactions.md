# 0003: manual edits of redacted files are the base of later runs

Status: accepted.

## Context

Rules cannot remove everything: headers, footers, logos and names inside pictures are not text
rules. The usual way to deal with them is to open the redacted file (double-click in the GUI),
draw boxes in Stirling-PDF's manual redaction and save over the file in `redacted/`.

While doing so, the user often finds text that belongs in the folder context. Adding it and running
again redid the file **from the original**, so every box had to be drawn again, after each new
term. This happened silently: the ledger did not know what the run had written, and when a new term
changed the redacted name, the edited output was even deleted as an orphan.

## Options considered

1. **Hook into Stirling's viewer** to record the boxes. Rejected: the desktop and viewer code is in
   large part under Stirling's proprietary licence (see `stirling-notes.md`) and changes with every
   weekly release.
2. **Read the boxes back from Stirling and replay them through its API.** Rejected:
   - no API reports what was drawn in the viewer, and after "apply" the saved file holds no record
     of the areas;
   - the area endpoints (`/api/v1/security/redact`, `imageBoxes` of `redact-execute`) only append a
     filled rectangle: the content underneath stays extractable
     ([`ManualRedactionService.java` at v3.1.0](https://github.com/Stirling-Tools/Stirling-PDF/blob/v3.1.0/app/core/src/main/java/stirling/software/SPDF/controller/api/security/ManualRedactionService.java),
     [`RedactExecuteService.java`](https://github.com/Stirling-Tools/Stirling-PDF/blob/v3.1.0/app/core/src/main/java/stirling/software/SPDF/controller/api/security/RedactExecuteService.java)).
     Replaying boxes that way is not redaction.
3. **An internal editor** that keeps areas as coordinates and removes their content itself. The
   right long-term answer, but a large piece of work: tracked separately as a follow-up.
4. **Rebase on the manual edit** (chosen now): keep the edited file and apply the rules on top of it.

## Decision

- The ledger stores the SHA-256 of each output (`output_sha256`). An output that no longer matches
  was edited after the run.
- At the start of `run`, before any output is replaced or removed, every edited output is copied to
  `<workspace>/manual/<original path>` and recorded in `manual.json`, together with the digests of
  the rules it had already been through (looked up in `rulesets.json` by the ledger's context
  fingerprint).
- When the file is redone, the engine starts from the manual copy instead of the original, with
  the full current context, provided that:
  - the original is the one the edit was made on;
  - the engine implements `rule_digests(ctx)` (Stirling: one digest per pattern actually sent);
  - the rules applied before the edit are a subset of the current ones.

  Otherwise the edit is marked stale with a reason (`original changed`, `engine cannot rebuild on top
  of it`, `rules removed`) and the file is redone from the original. The copy stays in `manual/`.
- A fresh edit always triggers a run of that file, even if nothing else changed: the user's file is
  sanitised and verified like any engine output. `--force` keeps the manual base.
- `publish` holds back a file edited after the last run (`edited after the last run: run Redact +
  verify first`).
- `reset-manual` (GUI: *Discard manual edits*) forgets an edit on purpose.

### Why "rules removed" drops the edit

Re-applying a superset of rules is idempotent, so rebasing never leaks: with fewer rules it would
only keep *more* redacted. But a rule is usually removed because it was wrong or too broad, and the
user expects its redactions to go away. Dropping is the expected outcome; the copy is kept to show
where the boxes were.

### Privacy

`manual.json` is keyed by original path, like `ledger.csv`; both live in the private workspace.
Rules are stored only as digests. Console and GUI report counts and fixed reason labels, never a
name or a value.

## Known limit

Verification checks text against the rules. It cannot tell whether the content under a manual box
(a logo, a header that is not a term) was removed or only covered: that depends on the tool used to
draw the box. Per-area validation needs the areas as data, which is the follow-up below.

## Follow-up

Internal editor: areas kept as coordinates, redaction and per-area validation at publish
(tracked in a GitHub issue).
