# Stirling-PDF as a redaction engine: what we use and what we avoid

pdf-toolkit sends PDFs to a **self-hosted Stirling-PDF on 127.0.0.1** for redaction. These notes
come from reading the Stirling-PDF source at tag
[`v3.1.0`](https://github.com/Stirling-Tools/Stirling-PDF/tree/v3.1.0) (October 2026). Re-check them
when upgrading Stirling.

## Why not a fork

| Need | Stirling v3.1.0 |
|---|---|
| Open a folder from disk | Desktop app only, in [`frontend/editor/src/desktop/`](https://github.com/Stirling-Tools/Stirling-PDF/tree/v3.1.0/frontend/editor/src/desktop), which is under the proprietary licence. The MIT core has a stub ([`localFolderContents.ts`](https://github.com/Stirling-Tools/Stirling-PDF/blob/v3.1.0/frontend/editor/src/core/services/localFolderContents.ts), `canListDirectory = false`). |
| Batch processing of folders | "Processor" / policies / watched folders: proprietary, and they need a signed-in server or the cloud ([`operationRouter.ts` L34-52](https://github.com/Stirling-Tools/Stirling-PDF/blob/v3.1.0/frontend/editor/src/desktop/services/operationRouter.ts#L34-L52)). Since 3.1.0 watched folders keep copies of the originals for 7 days (PR #8165). |
| Redact CSV, text, file names | Not available. |
| Licence | MIT except `app/proprietary`, `app/saas`, `engine/` and several `frontend/editor/src/*` folders ([LICENSE](https://github.com/Stirling-Tools/Stirling-PDF/blob/v3.1.0/LICENSE)). A core-only build exists (`STIRLING_FLAVOR=core`), but a fork means about 8,000 Java/TypeScript/Rust files with weekly releases. |

In the desktop app in cloud mode, tools not available locally are sent to the Stirling cloud
([`operationRouter.ts` L250-281](https://github.com/Stirling-Tools/Stirling-PDF/blob/v3.1.0/frontend/editor/src/desktop/services/operationRouter.ts#L250-L281)).
pdf-toolkit therefore talks only to the HTTP API of a local server.

## Endpoints

| Endpoint | Use | Notes |
|---|---|---|
| `POST /api/v1/security/auto-redact` | default engine | Uses JPDFium (MIT, PDFium-based) with `removeContent(true)` and `redactMetadata(true)` ([`RedactController.java` L212-229](https://github.com/Stirling-Tools/Stirling-PDF/blob/v3.1.0/app/core/src/main/java/stirling/software/SPDF/controller/api/security/RedactController.java#L212-L229)). One regex per line in `listOfText`. |
| `POST /api/v1/security/redact-execute` | alternative (`endpoint = "redact-execute"`) | Separate exact strings and regexes, page wipes, `redactImagePages` ([`RedactExecuteRequest.java`](https://github.com/Stirling-Tools/Stirling-PDF/blob/v3.1.0/app/core/src/main/java/stirling/software/SPDF/model/api/security/RedactExecuteRequest.java)). |
| `POST /api/v1/security/sanitize-pdf` | after redaction | JavaScript, embedded files, XMP, metadata, links removed. |
| `POST /api/v1/security/redact` and `imageBoxes` of `redact-execute` | **not used** | Areas by coordinates. They only **append a filled rectangle** to the page: the text, images and paths underneath stay in the file ([`ManualRedactionService.java`](https://github.com/Stirling-Tools/Stirling-PDF/blob/v3.1.0/app/core/src/main/java/stirling/software/SPDF/controller/api/security/ManualRedactionService.java) `redactAreas`, `redactImageBoxes`), unless the whole document is rasterised (`convertPDFToImage`). Not a way to replay manual boxes: see `docs/decisions/0003-manual-redactions.md`. |
| `GET /api/v1/info/status` | `pdf-toolkit redact stirling-status` | Version and health. |

## Pitfalls and how pdf-toolkit handles them

- **Silent fallback.** If JPDFium fails, `auto-redact` falls back to the older manual redaction
  without telling the caller ([L261-280](https://github.com/Stirling-Tools/Stirling-PDF/blob/v3.1.0/app/core/src/main/java/stirling/software/SPDF/controller/api/security/RedactController.java#L261-L280)).
  Text may remain under the boxes. → Every output is verified (`pdf_redaction.verify`) with two
  independent extractors; leftover text means FAIL and the file is never published.
- **Regex dialect: rules dropped silently.** Measured on 3.1.0 with `auto-redact`: a pattern that
  contains a `\uXXXX` escape or the `u` inline flag (`(?u)`, `(?iu:...)`) is ignored without any
  error, while the other patterns of the same request still apply. `(?i:...)`, look-arounds,
  `\x{hh}` and Latin-1 ranges such as `À-ÿ` work; matching is case-insensitive even without flags.
  → `rules/java_regex.py` rewrites `\uXXXX` as `\x{hh}`, uses `(?i:...)` only and refuses any
  pattern that would still be dropped; the test double of Stirling drops such rules the same way.
  Re-test this list when upgrading.
- **File names in logs.** `auto-redact` logs the uploaded file name at INFO
  ([L251-254](https://github.com/Stirling-Tools/Stirling-PDF/blob/v3.1.0/app/core/src/main/java/stirling/software/SPDF/controller/api/security/RedactController.java#L251-L254)).
  → The client always uploads the file as `document.pdf`; the compose template sets the log level to WARN.
- **Patterns in logs and errors.** At DEBUG the redaction terms are logged; an invalid regex is
  echoed in the error body. → DEBUG stays off; the client never surfaces response bodies.
- **Usage metering.** Since 3.0 the API, Processor and AI share a free allowance of 1,000 units a
  month. While the instance is not linked to stirling.com the counter is local; the daily sync
  ([`AccountLinkClient.java` L360-410](https://github.com/Stirling-Tools/Stirling-PDF/blob/v3.1.0/app/proprietary/src/main/java/stirling/software/proprietary/accountlink/AccountLinkClient.java#L360-L410))
  sends unit counts only, and only for linked instances. → Never link the instance ("Connect");
  metering is switched off in the compose template. `pdf-toolkit redact run` prints how many remote
  calls it made (one for redaction, one for sanitising, per PDF); unchanged files are skipped.
  When the allowance is used up, every call answers `HTTP 402` until the next month. Ways out, and
  the plan to stop depending on it: [migration guide](migration-guide.md#rolling-back-to-2143-no-usage-limit),
  [decision 0004](decisions/0004-local-redaction-engine.md).
- **Fonts with custom encodings and scans.** Text that cannot be extracted cannot be matched.
  → Verification warns about pages without text and pages with images: those need a visual check.

## Upgrade checklist

1. Check the new tag on Docker Hub and read the release notes for redaction, logging, metering.
2. Re-read `RedactController`, `RedactExecuteService`, `AccountLinkProperties` at the new tag.
   Re-check the regex dialect (see "Regex dialect" above) on a synthetic PDF.
3. Back up the folder that holds Stirling's `configs/` (users, API keys, settings): newer versions
   migrate its database and you cannot go back without the copy.
4. Change the tag in your compose file and run `docker compose up -d` from its folder: compose
   recreates the container on the new image and keeps `configs/`, so the API key stays valid.
   Keep the old image until the checks below pass (`docker images`), then `docker rmi` it.
5. Run `pdf-toolkit redact stirling-status` (it prints the version), then a session on synthetic
   documents (`scripts/make_demo_folder.py`) and check that it ends OK.
6. Re-run real sessions with `redact run SESSION --force`: the engine settings did not change, so
   without `--force` already redacted files would be kept as they are.

Rollback: stop the container, restore the `configs/` backup, put the old tag back, `docker compose up -d`.
