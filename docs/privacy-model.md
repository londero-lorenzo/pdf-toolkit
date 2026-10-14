# Privacy model

## Places

| Place | Contains | Who may read it |
|---|---|---|
| **Source folder** | original documents + `.redaction/` (the folder context) | you only. pdf-toolkit only reads it (writes `.redaction/` when you edit the context) |
| **Workspace** (`workspace_root/<alias>`) | copy of the originals, redacted output, ledger, review marks, name preview | you only. Must not be inside a *protected location* |
| **Output** (`output_root/<alias>`) | verified files + text extracts | whoever you share it with |
| **Configuration** (`%APPDATA%/pdf-toolkit/config.toml`) | paths to your global term/alias lists, API key file | you only |

*Protected locations* are folders where unredacted data must never land: synced or shared
folders, the working directory of an AI assistant, a repository. The output root is protected
automatically. pdf-toolkit refuses to create a workspace inside one of them.

## Guarantees (each one is covered by tests)

- **Nothing private on screen output.** CLI lines and GUI dialogs carry status, rule labels
  (`term folder#3`, `TAX_CODE_IT`), counts and redacted paths. A redacted path that still matches a
  rule is shown as `file#N`. Unexpected exceptions show their type only (`--debug` shows more).
- **Source is never modified** (except `.redaction/` when you edit the context): tests hash the
  source tree before and after a full run.
- **One network module.** Only `pdf_redaction/engines/stirling.py` imports networking code (a test
  scans the whole repository). It accepts loopback URLs only and ignores proxy variables.
- **Neutral uploads.** Files are sent to Stirling as `document.pdf`; error bodies are never shown.
- **Verify before publish.** Publishing re-verifies each file with the current context; FAIL files,
  files redacted with older rules and unsupported file types are never published.
- **Incremental by fingerprint.** Each output records the SHA-256 of its original and the
  fingerprint of the rules; any change makes the file be redone.

## Limits (what needs a human)

- Text inside images, scans, signatures, stamps, logos, QR codes and barcodes cannot be matched:
  verification flags pages with images and pages without text as WARN.
- People's names that are not in any list cannot be guessed: use *Preview names* and read the
  verification output; add missing terms to the folder context.
- Weak patterns (long numbers, 11-digit numbers, landline-like numbers) may be amounts or codes:
  they give WARN, not FAIL.
- Unsupported file types (e.g. `.docx`, images) are skipped, never published.
