# Redaction guide: from a private folder to a shareable copy

This guide explains, step by step, how to turn a folder of private documents into a redacted
copy you can share. Every command also has `--help` (`uv run pdf-toolkit redact run --help`).

## The four places involved

```
SOURCE folder (your originals)           WORKSPACE (private, created by "new")
D:/originals/2025/                       <workspace_root>/invoices-2025/
  .redaction/   <- the folder context      session.json   which SOURCE, which alias
     terms.txt                             manifest.json  SHA-256 of every original
     aliases.csv                           originals/     byte-for-byte copy of SOURCE
     settings.toml                         redacted/      output of "run" (redacted names)
  statement_2025-12.pdf                    ledger.csv     what was redacted, with which rules
  movements.csv                            review.json    files you marked as reviewed
  ...                                      preview_names.csv (only after "preview-names")

OUTPUT folder (shareable, filled by "publish")
the destination you give with --to, e.g. E:/to-share/ (default: <output_root>/invoices-2025/)
```

| Place | Who writes it | Contains real data? |
|---|---|---|
| **Source** | you; pdf-toolkit only reads it (and creates `.redaction/` if you ask) | yes |
| **Context** (`<source>/.redaction/`) | you (or the GUI context editor) | yes: it lists what to hide |
| **Workspace** | pdf-toolkit | **yes** (the copy of the originals): keep it private |
| **Output** | `publish`, only with verified files | no |

The workspace and the output folder must not be inside the source, and the workspace must not be
inside `output_root` or any `protected_locations` (synced or shared folders): pdf-toolkit refuses
otherwise. The output folder is chosen when you publish; it must not contain or be inside the
source, the workspace or `workspace_root`. `protected_locations` do not apply to it: it only
receives verified files.

## Before the first session

1. `uv run pdf-toolkit config init`, then `uv run pdf-toolkit config edit` and set at least:

   ```toml
   [redaction]
   pattern_packs = ["common", "it"]          # built-in PII rules: e-mail, IBAN, tax codes...
   workspace_root = "D:/private/workspaces"  # where "new" creates workspaces
   output_root = "D:/share/redacted"         # optional: default for "publish" (<output_root>/<alias>)
   protected_locations = ["C:/Users/me/OneDrive"]

   [engines.stirling]
   api_key_file = "D:/private/stirling_api_key.txt"   # a file holding only the key
   ```

2. `uv run pdf-toolkit config check` and `uv run pdf-toolkit redact stirling-status`.

## Step 1: describe what to hide (the folder context)

```bash
uv run pdf-toolkit redact context "D:/originals/2025" --init
```

This creates `D:/originals/2025/.redaction/` with two empty files. Edit them with any text editor:

- `terms.txt`: one term per line. Matching ignores case and extra spaces; a full name also matches
  in reverse order (`Jane Example` finds `EXAMPLE JANE`), and a code also matches with separators
  (`00999888` finds `00 999 888`). Each term becomes `[REDACTED]` in contents and `REDACTED` in names.

  ```
  Jane Example
  XMPJNE85M41Z999K
  ```

- `aliases.csv`: `real,alias` per line, when you want a readable pseudonym instead of `[REDACTED]`:

  ```
  00999888777666555,POL-A
  ```

- `settings.toml` (optional, create it yourself or with the GUI):

  ```toml
  pattern_packs = ["common", "it"]   # overrides the configuration for this folder
  drop_columns = ["Holder"]          # CSV columns removed entirely
  ```

These rules are added to your global lists (`global_term_files`, `global_alias_files`) and to the
pattern packs. Run `redact context "D:/originals/2025"` again at any time to see how many rules
apply (counts only). The `.redaction/` folder is never copied into the workspace.

You can also do this step later: `run` always reads the current context.

## Step 2: `redact new` - create the session

```
uv run pdf-toolkit redact new SOURCE ALIAS [--workspace FOLDER]
```

| Argument | Meaning |
|---|---|
| `SOURCE` | the folder of originals. It is only read. Sub-folders are included. |
| `ALIAS` | a **public** short name for this session: 1-64 letters, digits, `.`, `_`, `-`, starting with a letter or digit. It names the workspace (`<workspace_root>/<ALIAS>`) and the default publish folder (`<output_root>/<ALIAS>/`), so it must not contain anything personal: pdf-toolkit refuses an alias that matches a redaction rule. Examples: `invoices-2025`, `contracts_q3`. |
| `--workspace FOLDER` | optional: put the workspace somewhere else than `<workspace_root>/<ALIAS>`. Needed only if `workspace_root` is not configured. |

What it does:

1. checks the alias and the locations (see "The four places" above);
2. creates the workspace and copies every file of SOURCE into `originals/` (except `.redaction/`);
3. writes the manifest. **Nothing is redacted yet.**

Output: `session 'invoices-2025' created: 12 files copied to its workspace`.

You run `new` **once per source folder**. If the source changes later (new, modified or deleted
files) you do not need a new session: the next `run` copies the changes. To start from scratch,
delete the workspace folder and run `new` again.

Common errors:

| Message | Fix |
|---|---|
| `alias: use 1-64 letters...` | choose a simpler alias |
| `alias matches a redaction rule` | the alias contains a term, an alias value or a long code: choose a neutral one |
| `a session already exists in this workspace` | use `run ALIAS`, or pick another alias |
| `workspace is inside protected location #N` / `source and workspace must not contain each other` | move `workspace_root` (or `--workspace`) to a private folder outside the source and the output |
| `redaction.workspace_root is not set` | set it with `config edit`, or pass `--workspace` |

## Step 3 (optional): `redact preview-names`

```bash
uv run pdf-toolkit redact preview-names invoices-2025
```

Writes `preview_names.csv` (original name; redacted name) **in the workspace** so you can check the
renaming before running. It prints only counts. Open the CSV yourself: it contains real names.

## Step 4: `redact run` - redact and verify

```
uv run pdf-toolkit redact run SESSION [--force]
```

| Argument | Meaning |
|---|---|
| `SESSION` | the alias given to `new` (looked up in `workspace_root`), or the path of the workspace folder |
| `--force` | redo every file, even those already done with the same rules |

What it does, in order:

1. **Syncs the originals**: copies new or modified files from SOURCE, removes the copies of deleted ones.
2. **Loads the context** (global lists + `<source>/.redaction/` + pattern packs).
3. **Plans the names**: every folder and file name is redacted (terms, aliases, PII, codes of 6+ digits;
   dates like `2025-12` or `20251231` are kept). Two names that become equal get `_2`, `_3`...
4. **Redacts each file** into `redacted/`, several at a time (`workers` in the configuration):
   - `.pdf` -> Stirling-PDF (text removal, then sanitising: metadata, attachments, scripts, links);
   - `.csv`, `.tsv`, `.txt`, `.md` -> built-in text engine;
   - any other type -> `SKIP`: not processed and never published.
5. **Verifies** every output (two PDF text extractors, metadata, annotations, forms, attachments, the name).

It is **incremental**: a file is skipped (counted as `unchanged`, but verified again) when its
original, the rules and the engine settings are the same as last time. Change `terms.txt`
and the next `run` redoes everything, printing `note: rules changed since the last run`.
Use `--force` only when something pdf-toolkit cannot see has changed, for example after upgrading
Stirling-PDF, or if you edited files inside `redacted/` by hand.

### Reading the output

```
OK   statements/statement_2025-12.pdf
WARN ABCDEPOL-A.pdf: images on p1
FAIL file#3: p2: term folder#2 x2
SKIP notes.docx: file type not supported, not processed
ERR  file#5: Stirling answered HTTP 401 on /api/v1/security/auto-redact (missing or wrong API key)
4 redacted, 0 unchanged, 1 unsupported, 1 errors; remote engine calls: 8
--- 4 files: 2 OK, 1 WARN, 1 FAIL
```

- Paths are the **redacted** ones. `file#N` replaces a path that still matches a rule, or one that is
  not shown on errors.
- Findings say *where* (`p2` = page 2, `metadata`, `name`, `text` for text and CSV files...),
  *which rule* and *how many times*. The matched text is never printed. Rules are named by file and
  **line number**: `term folder#2` = line 2 of the folder's `terms.txt` (line 1 is the comment
  written by `--init`), `alias folder-alias#3` = line 3 of `aliases.csv`, `term global#5` = line 5 of
  your global term file; built-in patterns have names such as `EMAIL`, `IBAN`, `TAX_CODE_IT`.
- **OK**: nothing found. **WARN**: a person must look at it (images or scans, which text extraction
  cannot check; weak hits such as long numbers; annotations, forms, attachments). **FAIL**: a rule
  still matches, or the file cannot be checked (encrypted, unreadable): it will not be published.
- `remote engine calls`: requests sent to the local Stirling (usually 2 per PDF: redact + sanitize).

Exit code: `0` all OK, `2` some WARN, `1` any FAIL or error.

### What to do next

| You see | Do |
|---|---|
| `FAIL ... term/alias ...` in a PDF | Stirling left text behind. Check that you run the latest pdf-toolkit (older versions sent rules Stirling 3.1 ignores), then try `endpoint = "redact-execute"` in `[engines.stirling]`, run again (it redoes the PDFs automatically, since the engine settings changed) |
| `FAIL ... name: ...` | improve the rule or add a term/alias for the part of the name that leaks, then `run` |
| `WARN ...: images on p1` | open `redacted/<path>` in the workspace, check the images by eye, then `redact review SESSION "<path>"` |
| `WARN ...: LONG_NUMBER` | a weak hit: check whether it is personal. If yes add it to `terms.txt` or `aliases.csv` and `run`; if not, `review` it |
| `ERR ...: HTTP 401` | API key missing or wrong (`api_key_file`) |
| `ERR ...: Stirling not reachable` | Stirling is not running: `docker compose up -d`, then `redact stirling-status` |
| `SKIP` | convert the file to PDF or text, or leave it out: skipped files are never published |

`uv run pdf-toolkit redact verify SESSION` repeats only the checks (no copy, no redaction) and
prints the same lines: useful after you changed something by hand.

## Step 5: `redact review` - confirm the WARN files yourself

```
uv run pdf-toolkit redact review SESSION PATH [PATH ...] [--undo]
```

**Why it exists.** The checks read the *text* of a file. Some things cannot be judged that way:

- a page with an image or a scan: a name may be inside the picture, where no extractor sees it;
- a weak hit, such as `LONG_NUMBER`: a long number may be a contract number or just an amount;
- annotations, form fields, attachments.

For these files `run` says WARN instead of OK, and `publish` will not copy them until a person
has looked at them. `review` is how you say "I looked, it is fine".

| Argument | Meaning |
|---|---|
| `SESSION` | as for `run` |
| `PATH` | the redacted path **exactly as printed by `run`** (`ABCDEPOL-A.pdf`, `statements/statement_2025-12.pdf`). Quote it if it has spaces. `\` is accepted instead of `/`. Several paths at once are fine. |
| `--undo` | remove the mark (you marked the wrong file, or changed your mind) |

How to do it:

1. Open `<workspace>/redacted/<PATH>` (not the original!) in your PDF viewer.
2. Look at the pages the WARN names (`images on p1` = page 1). Is anything personal visible: a name
   in a scanned signature, a code in a picture, a stamp?
   - **Nothing personal**: `uv run pdf-toolkit redact review invoices-2025 "ABCDEPOL-A.pdf"`.
     Output: `1 file(s) marked as reviewed`. From now on `run` and `verify` print
     `WARN ABCDEPOL-A.pdf (reviewed): images on p1`.
   - **Something personal in an image**: do not review it. Text rules cannot remove it, because
     it is not text. Leave the file out of the source, or replace it with a version where the image
     is covered, then `run` again.
   - **A weak hit that is personal**: add it to `terms.txt` or `aliases.csv`, then `run`.

The mark is tied to the **content** of the redacted file, not just to its name: if a later `run`
produces a different file (new version in the source, new rules, other engine), the mark no longer
applies and you will be asked to look again. Marks are stored in `<workspace>/review.json`.

Marking OK or FAIL files does nothing: OK files do not need it, and FAIL files are never published.
If `review` answers `path(s) not found among the redacted files`, copy the path from the output of
`run` again (exit code 1). A path printed as `file#N` cannot be reviewed: its name still matches
a rule, so it is a FAIL anyway.

## Step 6: `redact publish` - copy the safe files out

```
uv run pdf-toolkit redact publish SESSION [--to FOLDER]
```

**Why it exists.** The workspace is private: it contains the originals. `publish` is the only step
that writes outside of it, into a folder you can share, send or upload, and it lets through only
files that pass the checks *at that moment*.

| Argument | Meaning |
|---|---|
| `SESSION` | as for `run` |
| `--to FOLDER` | publish **exactly** into `FOLDER` (no `<ALIAS>` sub-folder) and remember it for this session. Without it: the destination used last time, else `<output_root>/<ALIAS>` if `output_root` is set, else an error. It must not contain or be inside the source, the workspace or `workspace_root`. |

The GUI asks for the destination in the Publish step (pre-filled with the one above, "Browse..." to
change it). Design notes: `docs/decisions/0001-publish-destination.md`.

What it does, for every file of the session:

1. holds it back if the rules or the original changed after it was redacted (`terms.txt` edited, a
   new version of the file in the source): run `run` first. Files that were never redacted (`SKIP`,
   or `ERR` on the first attempt) are not part of the result at all and are simply not published;
2. **verifies it again** with the current rules;
3. copies it if it is **OK**, or **WARN and reviewed**; FAIL files and WARN files not reviewed stay out;
4. for PDFs, also writes the extracted text to `_text/<PATH>.txt` (checked too). This is handy for
   searching the documents or giving them to tools that read only text.

`publish` does **not** redact and does **not** read the source: always `run` before `publish`.

Result:

```
<destination>/
  statements/statement_2025-12.pdf
  movements.csv
  ABCDEPOL-A.pdf                         (only once reviewed)
  _text/statements/statement_2025-12.pdf.txt
  _text/ABCDEPOL-A.pdf.txt
  .published.json                        owner (the alias) and list of files written by this session
```

Output on the console:

```
destination (--to): E:/to-share
HOLD ABCDEPOL-A.pdf: WARN: mark it as reviewed first
HOLD file#2: verification FAIL
2 published, 2 held back, 0 stale removed
```

`destination (...)` says where the folder came from: `--to`, `last used` or `output_root/<alias>`.
The folder path is printed unless a part of it matches a redaction rule; then it reads
`(folder hidden: its path matches a redaction rule)`.

As in `run`, `file#N` replaces a path that still matches a rule, and no file content is printed.

| HOLD reason | Do |
|---|---|
| `WARN: mark it as reviewed first` | Step 5 |
| `verification FAIL` | see "What to do next" in Step 4 |
| `rules changed since it was redacted: run again` | `redact run SESSION`, then publish |
| `source changed since it was redacted: run again` | `redact run SESSION` (if it shows `ERR` for the file, see Step 4) |
| `not redacted yet` | the redacted file is missing from the workspace: `redact run SESSION` |
| `text extract FAIL` | the PDF passed but its text extract did not: treat it like a FAIL |
| `a file not written by pdf-toolkit is in the way` | the destination already has a file with that name: rename or move it, or publish elsewhere (it is never overwritten) |

Exit code: `0` everything published, `2` something held back.

You can publish **as often as you like**. Each time the output folder is brought in line with the
session: changed files are overwritten, and files this session published earlier that no longer
qualify (deleted from the source, now FAIL, review undone) are **removed**. Files that are in the
same folder but were not written by `publish` are never deleted or overwritten (`note: the
destination holds N file(s) not written by pdf-toolkit: left untouched`). A folder published by
another session is refused. So do not edit files that `publish` wrote: copy them elsewhere first.

**Changing the destination.** Publish with another `--to` and the session remembers the new
folder. The old one is left exactly as it was, and the console tells you where it is and how many
files were published there, so you can remove them yourself:

```
note: destination changed; the previous one was left as it was: E:/to-share (14 file(s) published there)
```

## Cheat sheet

```bash
uv run pdf-toolkit redact context "D:/originals/2025" --init   # once: create .redaction/
# ... edit .redaction/terms.txt and aliases.csv ...
uv run pdf-toolkit redact new "D:/originals/2025" invoices-2025 # once: create the session
uv run pdf-toolkit redact preview-names invoices-2025           # optional: check new names
uv run pdf-toolkit redact run invoices-2025                     # every time something changed
uv run pdf-toolkit redact review invoices-2025 "scan.pdf"       # after looking at a WARN file
uv run pdf-toolkit redact publish invoices-2025 --to "E:/to-share"  # copy OK and reviewed files out
uv run pdf-toolkit redact publish invoices-2025                 # again: same destination as last time
```
