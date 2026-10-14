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
| `GET /api/v1/info/status` | `pdf-toolkit redact stirling-status` | Version and health. |

## Pitfalls and how pdf-toolkit handles them

- **Silent fallback.** If JPDFium fails, `auto-redact` falls back to the older manual redaction
  without telling the caller ([L261-280](https://github.com/Stirling-Tools/Stirling-PDF/blob/v3.1.0/app/core/src/main/java/stirling/software/SPDF/controller/api/security/RedactController.java#L261-L280)).
  Text may remain under the boxes. → Every output is verified (`pdf_redaction.verify`) with two
  independent extractors; leftover text means FAIL and the file is never published.
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
- **Fonts with custom encodings and scans.** Text that cannot be extracted cannot be matched.
  → Verification warns about pages without text and pages with images: those need a visual check.

## Upgrade checklist

1. Check the new tag on Docker Hub and read the release notes for redaction, logging, metering.
2. Re-read `RedactController`, `RedactExecuteService`, `AccountLinkProperties` at the new tag.
3. Run `pdf-toolkit redact stirling-status`, then a session on synthetic documents and verify.
