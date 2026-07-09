# DOCX CV Upload Support Implementation Plan

## Overview

Extend CV upload/ingestion to accept `.docx` (modern Word Open XML) alongside
the currently-supported PDF, via a lightweight pure-Python text/structure
extraction path — no office-rendering engine (LibreOffice/MS Word), no
legacy `.doc` support.

## Current State Analysis

CV upload is PDF-only at three layers today:

- **Frontend**: two independently duplicated upload widgets —
  `frontend/app/dashboard/cv/page.tsx` (standalone CV page) and
  `frontend/app/dashboard/page.tsx` (`useCvUpload`/`CvUploadPanel`, embedded
  in the main dashboard) — each with its own `file.type !== "application/pdf"`
  check, `accept=".pdf"` input, and PDF-only copy.
- **Backend upload** (`src/api/routes/cv.py`, `upload_cv`): rejects any
  `file.content_type != "application/pdf"` (line 120), validates PDF magic
  bytes `%PDF` (line 132), hardcodes the saved filename extension to `.pdf`
  (line 153).
- **Ingestion pipeline** (`src/tools/vectordb.py`, `CVVectorManager`):
  `ingest_cv_async` renders PDF pages to images (`_pdf_to_base64_images`),
  runs vision-based CV detection (`_detect_if_cv`) on page 0, then
  per-page Vision LLM OCR (`_process_single_page`) to build a Markdown
  `full_text` string, which is then Markdown-header-split and
  recursive-character-chunked, embedded, and stored in pgvector.

## Desired End State

A user can upload a `.docx` CV through either dashboard upload widget. The
backend accepts it (content-type + structural validation), extracts its
text/headings/tables into the same Markdown `full_text` shape the PDF path
already produces, runs it through the unchanged chunking/embedding/pgvector
pipeline, and the resulting CV context is retrievable by the Orchestrator
exactly as a PDF-derived CV would be. PDF upload behavior is unchanged.
Verify by: uploading a real `.docx` CV via `/dashboard/cv`, confirming
`ingestion_status` reaches `completed`, and confirming the Orchestrator's RAG
lookup returns non-empty, sensible context for that user afterward.

### Key Discoveries:

- `full_text` is the convergence point: everything after it (Markdown header
  split, `RecursiveCharacterTextSplitter`, `_split_experience_block`,
  embedding, pgvector storage) is already format-agnostic —
  `src/tools/vectordb.py:209-298`.
- `python-docx`'s `paragraph.text` does **not** include the bullet
  glyph/number for `List Bullet`/`List Number` styled paragraphs — those are
  rendered via Word's numbering XML (`numPr`), not literal text runs. Bullet
  markers must be reconstructed from `paragraph.style.name`, not assumed
  present in the text.
- The existing text-cache short-circuit (`vectordb.py:178-184`,
  `cv_text_cache_path`) is already format-agnostic — it caches the *output*
  Markdown, not the source file — so no changes needed there.
- `context/foundation/lessons.md` "Exception Handling: Distinguish
  Recoverable from Critical Errors" applies directly to the new docx-parsing
  failure paths: recoverable content issues must raise `ValueError` (the
  existing contract `_ingest_cv_background`, `src/api/routes/cv.py:51-61`,
  already uses to surface `CVFile.ingestion_error`), not fall through to a
  bare `except Exception`.
- mypy is strict (`disallow_untyped_defs`) and no `ignore_missing_imports`
  override exists in `pyproject.toml`; `pdf2image` currently passes `mypy`
  cleanly (verified: `uv run mypy src/tools/vectordb.py` → success), so it
  ships usable type information. `python-docx`'s stub situation is unverified
  until the dependency is actually added — see Critical Implementation
  Details.

## What We're NOT Doing

- Legacy `.doc` (binary OLE format) — no viable pure-Python parser exists;
  would require LibreOffice or `antiword`, rejected as disproportionate for
  this app's size.
- Any office-rendering engine (LibreOffice, MS Word, `unoconv`,
  `pdfconverter`, `docx2pdf`) — every such tool shells out to a real office
  suite under the hood; none are pure-Python.
- A shared frontend validation function/hook — only the allowed-extensions/
  MIME/copy constants are consolidated (`frontend/lib/cv-upload.ts`); each
  widget keeps its own independent `uploadFile`/`upload` validation logic.
- An automated Playwright test exercising a real `.docx` upload through the
  browser — deferred to a follow-up `/10x-e2e` run per this project's
  established risk→seed→generate→review E2E workflow (see root `CLAUDE.md`).
  This plan's own verification is unit/integration tests + manual checks.
- Any change to Markdown table rendering fidelity — tables flatten to
  pipe-separated plain-text lines, not real Markdown table syntax (rejected:
  the splitters aren't table-aware and could break a real Markdown table
  mid-row).

## Implementation Approach

Add a second, parallel extraction path in `CVVectorManager` that produces the
same Markdown `full_text` shape the PDF path already produces, then dispatch
on file extension inside `ingest_cv_async` before the existing PDF logic
runs. Mirror the same allow/reject pattern at the upload boundary
(`cv.py`) with a stronger structural check (attempt to open the file with
`python-docx`) instead of a bare magic-byte check, since a zip signature
alone doesn't distinguish `.docx` from `.xlsx`/`.pptx`/`.odt`.

```
.pdf  → pdf2image → page images → Vision LLM OCR → Markdown  ┐
.docx → python-docx → paragraph/heading/table walk → Markdown ┴→ chunk → embed → pgvector
```

## Critical Implementation Details

**`python-docx` mypy stub risk**: unlike `pdf2image` (confirmed clean under
strict mypy), `python-docx`'s type-stub situation is unverified before this
plan runs. If `uv run mypy src/tools/vectordb.py` reports
`import-untyped`/`import-not-found` for `docx` after the dependency is added
in Phase 1, resolve it with a `# type: ignore[import-untyped]` comment on
the `from docx import Document as DocxDocument` line (matching the
narrowest possible fix) rather than a blanket `ignore_missing_imports` in
`pyproject.toml`. Do not skip this check — strict mode will fail CI on an
untyped import otherwise.

**Bullet reconstruction is required, not optional**: because
`paragraph.text` omits the bullet glyph for native Word list styles (see Key
Discoveries), `_docx_to_markdown` must explicitly prepend `"• "` for
paragraphs whose `style.name` starts with `"List"`. Skipping this silently
drops all visual bullet structure from list-formatted CV sections (most
commonly: skills lists, responsibilities under a role).

## Phase 1: Ingestion pipeline (`src/tools/vectordb.py`)

### Overview

Add the `python-docx` dependency and the docx extraction + text-based
CV-detection methods, then dispatch on file extension inside
`ingest_cv_async`.

### Changes Required:

#### 1. Add dependency

**File**: `pyproject.toml`

**Intent**: Make `python-docx` available for `.docx` parsing.

**Contract**: Add `"python-docx>=1.1.0"` to the `dependencies` array (near
the existing `pdf2image`/`pypdf` entries, `pyproject.toml:19-25`). Run
`uv sync` to update `uv.lock`.

#### 2. Docx-to-Markdown extraction

**File**: `src/tools/vectordb.py`

**Intent**: Convert a `.docx` file into the same Markdown shape
`_process_single_page`'s Vision-OCR output already produces, so it can flow
through the existing header-based chunking unchanged.

**Contract**: New static method `_docx_to_markdown(file_path: str) -> str`.
Import `from docx import Document as DocxDocument` at module level (aliased
to avoid clashing with the existing `langchain_core.documents.Document`
import at `vectordb.py:20`). Walk `document.paragraphs`; map
`paragraph.style.name`: `"Title"`/`"Heading 1"` → `# `, `"Heading 2"` →
`## `, `"Heading 3"` → `### `, any style starting with `"List"` → `"• "`
prefix (see Critical Implementation Details — this is load-bearing, not a
style choice), else plain paragraph text. Skip empty/whitespace-only
paragraphs. After paragraphs, flatten each `document.tables` row into one
line of `" | ".join(cell.text.strip() for cell in row.cells if
cell.text.strip())`, skipping empty rows. Join all lines with `"\n"`.

#### 3. Minimum-extractable-text guard

**File**: `src/tools/vectordb.py`

**Intent**: Give a clear, actionable error for content-sparse `.docx` files
(e.g. infographic-style CVs that are mostly embedded images) instead of
letting them fail confusingly downstream (empty chunks, meaningless
embeddings).

**Contract**: A module-level constant (e.g. `MIN_DOCX_TEXT_LENGTH = 100`)
checked immediately after `_docx_to_markdown` returns, inside
`ingest_cv_async`'s docx branch: if `len(full_text.strip()) <
MIN_DOCX_TEXT_LENGTH`, raise `ValueError("This DOCX has no extractable
text — try exporting as PDF instead.")` (recoverable per the lessons.md
rule — see Change #5 below).

#### 4. Text-based CV detection

**File**: `src/tools/vectordb.py`

**Intent**: Text-only sibling of the existing vision-based `_detect_if_cv`
(`vectordb.py:107-127`), since the docx path never produces a page image.

**Contract**: New instance method `_detect_if_cv_from_text(self, text: str)
-> None`. Same `CVDetectionResult` structured-output contract and same
`ValueError`-on-rejection behavior as `_detect_if_cv`, but builds a plain
text `HumanMessage` (send the first ~2000 chars of `text`, not an image
block) via `self.vision_model.with_structured_output(CVDetectionResult)` —
reuse the existing model instance; no new model wiring needed.

#### 5. Format dispatch in `ingest_cv_async`

**File**: `src/tools/vectordb.py`

**Intent**: Route `.docx` files through the new extraction path and PDFs
through the existing one, converging on `full_text` before the unchanged
chunking code.

**Contract**: In the "no cache" branch of `ingest_cv_async`
(`vectordb.py:185-207`), branch on `os.path.splitext(file_path)[1].lower()`
before the existing `_pdf_to_base64_images` call:
- `.docx` → call `_docx_to_markdown`, apply the minimum-text guard, then
  `_detect_if_cv_from_text` on the result. Wrap the `DocxDocument(...)` open
  call specifically: catch `docx.opc.exceptions.PackageNotFoundError` (the
  documented python-docx exception for "not a valid Office Open XML
  package") and re-raise as `ValueError(...)` — recoverable, matches the
  lessons.md distinction, and reuses the existing `_ingest_cv_background`
  `except ValueError` branch (`cv.py:51-61`) to surface it as
  `CVFile.ingestion_error` instead of falling through to the generic
  `except Exception` 500-style failure at `cv.py:62-68`.
- anything else (PDF) → existing `_pdf_to_base64_images` → `_detect_if_cv`
  → per-page Vision OCR loop, byte-for-byte unchanged.
Both branches converge on `full_text`; the existing `_normalize_bullets` +
cache-write + Markdown-header-splitting + chunking code (`vectordb.py:202
-298`) runs unmodified for either format.

### Success Criteria:

#### Automated Verification:

- [ ] `uv run pytest tests/tools/ -v` passes, including new tests for
  `_docx_to_markdown` (headings/paragraphs/list-bullets/tables produce
  expected Markdown), `_detect_if_cv_from_text` (mocked LLM, `is_cv`
  True/False → doesn't raise/raises `ValueError`), the minimum-text guard,
  and the `PackageNotFoundError` → `ValueError` translation
- [ ] `uv run mypy src/tools/vectordb.py` passes (resolve any `docx` stub
  gap per Critical Implementation Details)
- [ ] `uv run black --check src/tools/vectordb.py`

#### Manual Verification:

- [ ] None required for this phase in isolation — exercised end-to-end in
  Phase 3

---

## Phase 2: Upload endpoint (`src/api/routes/cv.py`)

### Overview

Extend `upload_cv`'s validation to accept `.docx` alongside PDF, with a
structural (not just magic-byte) check, and stop hardcoding the `.pdf`
extension on the saved filename.

### Changes Required:

#### 1. Content-type allowlist

**File**: `src/api/routes/cv.py`

**Intent**: Replace the single-format check with an extensible allowlist
mapping accepted content types to their file extension.

**Contract**: Module-level constant
`ALLOWED_CONTENT_TYPES: dict[str, str] = {"application/pdf": ".pdf",
"application/vnd.openxmlformats-officedocument.wordprocessingml.document":
".docx"}` near `CV_UPLOAD_DIR`/`MAX_FILE_SIZE` (`cv.py:25-26`). Replace the
`file.content_type != "application/pdf"` check (line 120) with `file
.content_type not in ALLOWED_CONTENT_TYPES`; error message updated to "Only
PDF and DOCX files are allowed."

#### 2. Format-specific content validation

**File**: `src/api/routes/cv.py`

**Intent**: Validate the actual file bytes match the claimed type — magic
bytes for PDF (unchanged), and a stronger structural open-attempt for docx
since the zip signature alone (`PK\x03\x04`) doesn't distinguish `.docx`
from other zip-based Office formats.

**Contract**: Replace the PDF-only magic-byte check (`cv.py:131-135`) with a
branch on the resolved extension: PDF keeps `content.startswith(b"%PDF")`;
docx checks `content.startswith(b"PK\x03\x04")` **and** attempts
`DocxDocument(BytesIO(content))`, raising the same 400
`"Invalid file. Only PDF and DOCX files are allowed."` on any exception from
either check. Import `from io import BytesIO` and `from docx import
Document as DocxDocument`.

#### 3. Extension-aware filename

**File**: `src/api/routes/cv.py`

**Intent**: Stop hardcoding `.pdf` on the saved filename now that two
formats are accepted.

**Contract**: Replace `filename = f"resume_{timestamp}.pdf"` (`cv.py:153`)
with `filename = f"resume_{timestamp}{ALLOWED_CONTENT_TYPES[file
.content_type]}"`.

#### 4. Log/error copy

**File**: `src/api/routes/cv.py`

**Intent**: Keep user-facing and log messages accurate for the new format.

**Contract**: Update the `logger.warning` message at `cv.py:121` and the
`HTTPException` details at lines 124 and 134 to say "PDF or DOCX" instead of
"PDF".

### Success Criteria:

#### Automated Verification:

- [ ] `uv run pytest tests/test_cv_routes.py -v` passes, including new
  cases: valid `.docx` upload (build a minimal in-memory docx via
  `python-docx` in the test, as bytes), invalid content-type still
  rejected, `.docx` with a valid MIME/zip signature but corrupt internal
  structure rejected (exercises the `DocxDocument(...)` open-attempt check)
- [ ] `uv run mypy src/api/routes/cv.py` passes
- [ ] `uv run black --check src/api/routes/cv.py`

#### Manual Verification:

- [ ] None required for this phase in isolation — exercised end-to-end in
  Phase 3

---

## Phase 3: Frontend widgets + end-to-end verification

### Overview

Consolidate the allowed-extensions/MIME/copy constants both upload widgets
already duplicate, update both to accept `.docx`, fix the copy-coupled e2e
assertion, and do a full manual pass confirming both formats work through
the real UI.

### Changes Required:

#### 1. Shared constants

**File**: `frontend/lib/cv-upload.ts` (new)

**Intent**: Single source of truth for the accepted MIME types, `accept`
attribute string, and rejection-message copy, so the two widgets can't drift
out of sync on what's allowed.

**Contract**: Export `ALLOWED_CV_MIME_TYPES` (array or set containing
`"application/pdf"` and
`"application/vnd.openxmlformats-officedocument.wordprocessingml.document"`),
`ALLOWED_CV_ACCEPT` (`".pdf,.docx"` for the `<input accept>` attribute), and
`CV_TYPE_ERROR_MESSAGE` (`"Only PDF or DOCX files are accepted."`). Each
widget's own `uploadFile`/`upload` function keeps its independent
validation logic, now checking membership in `ALLOWED_CV_MIME_TYPES`
instead of a hardcoded string equality (per the "shared constants only"
decision — no shared validation function).

#### 2. Standalone CV upload page

**File**: `frontend/app/dashboard/cv/page.tsx`

**Intent**: Accept `.docx` uploads and reflect that in the UI copy.

**Contract**: `uploadFile`'s MIME check (line 51) uses
`ALLOWED_CV_MIME_TYPES`/`CV_TYPE_ERROR_MESSAGE` from the new constants file.
`<input accept=".pdf" .../>` (line 135) → `accept={ALLOWED_CV_ACCEPT}`.
Copy at lines 104-106 → "Upload your CV as a PDF or DOCX. It will be parsed
and embedded for semantic job matching." Copy at line 129 → ".pdf, .docx ·
max 10 MB".

#### 3. Dashboard-embedded CV upload panel

**File**: `frontend/app/dashboard/page.tsx`

**Intent**: Same acceptance/copy update as the standalone page, applied to
the duplicated widget embedded in the main dashboard.

**Contract**: `upload`'s MIME check (line 79) and `<input accept=".pdf"
.../>` (line 217) updated the same way as Change #2, using the same shared
constants. Copy at line 190 → "Drop your CV here, or browse". Copy at line
555 → "Upload your resume as a PDF or DOCX. It will be parsed and embedded
for semantic job matching." Fallback filename defaults `"resume.pdf"` at
lines 63 and 68 (used only when the backend status response hasn't
returned a filename yet) → generic `"resume"`, since the extension is no
longer guaranteed to be `.pdf`.

#### 4. E2E assertion text fix

**File**: `frontend/tests/e2e/user-data-isolation.spec.ts`

**Intent**: Keep the existing data-isolation spec passing after the "Drop
your PDF here" copy changes to the neutral "Drop your CV here" (Change #3).

**Contract**: Line 117's `page.getByText(/drop your pdf here/i)` →
`page.getByText(/drop your cv here/i)`.

### Success Criteria:

#### Automated Verification:

- [ ] `cd frontend && npm run lint` passes
- [ ] `cd frontend && npm run build` (or `tsc --noEmit`) passes with no
  type errors
- [ ] `cd frontend && npx playwright test tests/e2e/user-data-isolation.spec.ts`
  passes with the updated copy assertion

#### Manual Verification:

- [ ] Start backend + frontend (`docker-compose.dev.yml` or local `uv run`
  / `npm run dev`); upload a real `.docx` CV through `/dashboard/cv`;
  confirm it reaches `ingestion_status: completed`
- [ ] Upload the same `.docx` through the dashboard-embedded panel
  (`/dashboard`); confirm identical behavior
- [ ] Confirm job matching retrieves sensible CV context afterward (i.e.
  the Orchestrator's RAG lookup returns non-empty results for that user)
- [ ] Re-upload a PDF CV through both widgets to confirm the existing PDF
  path is unaffected by the dispatch change
- [ ] Attempt an upload of a non-CV `.docx` (e.g. a random Word document)
  and confirm the text-based CV-detection rejection surfaces a clear
  `ingestion_error`

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that
the manual testing was successful before considering the change complete.

---

## Testing Strategy

### Unit Tests:

- `_docx_to_markdown`: headings (`Title`/`Heading 1/2/3`) map to correct `#`
  levels; `List Bullet`-styled paragraphs get `"• "` prefixed; plain
  paragraphs pass through; tables flatten to pipe-separated lines; empty
  paragraphs/rows are skipped.
- `_detect_if_cv_from_text`: mocked LLM returning `is_cv=True` doesn't
  raise; `is_cv=False` raises `ValueError` with the LLM's reason.
- Minimum-text guard: text under `MIN_DOCX_TEXT_LENGTH` raises `ValueError`
  with the "no extractable text" message; text at/above the threshold
  proceeds.
- `ingest_cv_async` dispatch: `.docx` path calls `_docx_to_markdown` +
  `_detect_if_cv_from_text` and never calls `_pdf_to_base64_images`/
  `_detect_if_cv`; PDF path is unchanged (regression check).
- `PackageNotFoundError` → `ValueError` translation on a corrupt docx that
  passed upload-time validation.

### Integration Tests:

- `upload_cv` end-to-end with a valid in-memory `.docx`: 202 response, file
  saved with `.docx` extension, background ingestion queued.
- `upload_cv` with `.docx` content-type but corrupt/non-docx bytes: 400.
- `upload_cv` with an unsupported content-type (e.g. `text/plain`): 400
  (regression check on the allowlist rewrite).

### Manual Testing Steps:

1. Upload a real `.docx` CV via `/dashboard/cv`; watch it reach `completed`.
2. Upload the same file via the dashboard-embedded panel.
3. Trigger a job search workflow for that user; confirm the Orchestrator's
   match reasoning references real CV content (not empty/generic context).
4. Re-upload a PDF CV through both widgets; confirm no regression.
5. Upload a non-CV `.docx`; confirm a clear rejection reason surfaces.

## Performance Considerations

The docx path skips Vision LLM calls entirely (no per-page OCR), so it is
faster and cheaper per upload than the PDF path — no new performance risk
introduced.

## Migration Notes

No data migration needed. `CVFile.file_path` already stores an arbitrary
path string; existing PDF records are unaffected. The text cache
(`cv_text_cache_path`) is keyed by user, not by source format, and is
already invalidated on `replace_existing` uploads (`cv.py:178-182`) — no
change needed there.

## References

- Design decisions and rejected alternatives:
  `context/changes/docx-cv-upload-support/change.md`
- `_detect_if_cv` (vision-based sibling being mirrored):
  `src/tools/vectordb.py:107-127`
- `_ingest_cv_background` (ValueError vs generic Exception contract):
  `src/api/routes/cv.py:36-68`
- `context/foundation/lessons.md` — "Exception Handling: Distinguish
  Recoverable from Critical Errors"

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a
> step lands. Do not rename step titles.

### Phase 1: Ingestion pipeline (`src/tools/vectordb.py`)

#### Automated

- [x] 1.1 `uv run pytest tests/tools/ -v` passes (new docx/detection/guard/
  error-translation tests)
- [x] 1.2 `uv run mypy src/tools/vectordb.py` passes
- [x] 1.3 `uv run black --check src/tools/vectordb.py`

### Phase 2: Upload endpoint (`src/api/routes/cv.py`)

#### Automated

- [x] 2.1 `uv run pytest tests/test_cv_routes.py -v` passes (new docx
  upload/rejection cases)
- [x] 2.2 `uv run mypy src/api/routes/cv.py` passes
- [x] 2.3 `uv run black --check src/api/routes/cv.py`

### Phase 3: Frontend widgets + end-to-end verification

#### Automated

- [x] 3.1 `cd frontend && npm run lint` passes (adapted: repo has no `lint`
  script/ESLint config — ran `npm run type-check` instead, which passed)
- [x] 3.2 `cd frontend && npm run build` passes with no type errors
- [x] 3.3 `cd frontend && npx playwright test tests/e2e/user-data-isolation.spec.ts`
  passes

#### Manual

- [x] 3.4 Real `.docx` CV upload via `/dashboard/cv` reaches `completed`
- [x] 3.5 Same `.docx` upload via dashboard-embedded panel works identically
- [x] 3.6 Orchestrator RAG lookup returns non-empty CV context afterward
- [x] 3.7 PDF upload through both widgets still works (regression check)
- [x] 3.8 Non-CV `.docx` upload surfaces a clear `ingestion_error`
