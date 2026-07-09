---
change_id: docx-cv-upload-support
title: Add DOCX support to CV upload and ingestion
status: implemented
created: 2026-07-09
updated: 2026-07-09
archived_at: null
---

## Notes

### Context

The app currently only accepts PDF CVs. Upload is enforced PDF-only at three
layers: frontend MIME/`accept` checks (two independent, duplicated upload
widgets), backend content-type + magic-byte validation
(`src/api/routes/cv.py`), and the ingestion pipeline itself
(`src/tools/vectordb.py`), which renders PDF pages to images and OCRs them
with a Vision LLM.

We explored converting Word docs to PDF first (via `pdfconverter`,
`unoconv`, `docx2pdf`, etc.) to reuse the existing Vision pipeline unchanged,
but every one of those tools shells out to LibreOffice (or, on
Windows/macOS, real MS Word) under the hood — there is no pure-Python
document-rendering engine. That's an unacceptable dependency (400-600MB
image bloat) for this app's size. Decision: **support `.docx` only** (modern
Word Open XML), via pure-Python text/structure extraction — no `.doc`
(legacy binary format), no office-rendering engine of any kind. `.docx` text
extraction is also strictly better for a CV than image-OCR: heading levels
come from the file's own paragraph styles instead of being guessed from
pixels.

### Approach

Add a second, lightweight ingestion path that runs entirely in Python,
parallel to (not replacing) the existing PDF→image→Vision-OCR path. The two
paths converge at "produce Markdown `full_text`", after which every
downstream step (header-based chunking, embeddings, pgvector storage,
retrieval) is already format-agnostic and needs zero changes.

```
.pdf  → pdf2image → page images → Vision LLM OCR → Markdown  ┐
.docx → python-docx → paragraph/heading/table walk → Markdown ┴→ chunk → embed → pgvector
```

New dependency: `python-docx` (pure Python, MIT license, no system binary).

### Backend changes

**`src/tools/vectordb.py` (`CVVectorManager`)**

- New `_docx_to_markdown(file_path: str) -> str` (static): opens the file
  with `python-docx`, walks `document.paragraphs`, maps paragraph
  `style.name` to Markdown (`Title`/`Heading 1` → `#`, `Heading 2` → `##`,
  `Heading 3` → `###`, `List*` styles → `• `, else plain text), and flattens
  `document.tables` rows into pipe-separated lines. Import `docx.Document`
  aliased (e.g. `DocxDocument`) to avoid clashing with the existing
  `langchain_core.documents.Document` import.
- New `_detect_if_cv_from_text(self, text: str) -> None`: text-only sibling
  of the existing `_detect_if_cv` (`vectordb.py:107-127`). Same
  `CVDetectionResult` structured output and same `ValueError`-on-rejection
  contract, but sends a plain text `HumanMessage` (first ~2000 chars)
  instead of an image — no vision call needed.
- `ingest_cv_async` (`vectordb.py:170-207`): in the "no cache" branch, add a
  format dispatch on the file extension before the existing PDF logic:
  - `.docx` → `_docx_to_markdown` → `_detect_if_cv_from_text` on the result.
  - anything else (PDF) → existing `_pdf_to_base64_images` →
    `_detect_if_cv` → per-page Vision OCR loop, unchanged.
  Both branches converge on `full_text`, which then goes through the
  existing `_normalize_bullets` + cache-write + Markdown-header-splitting +
  chunking code untouched.

**`src/api/routes/cv.py` (`upload_cv`)**

- Replace the single `file.content_type != "application/pdf"` check
  (line ~120) with an allowlist dict:
  `{"application/pdf": ".pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx"}`.
- Replace the PDF-only magic-byte check (line ~132) with a format-specific
  check: PDF keeps `content.startswith(b"%PDF")`; DOCX checks the zip
  signature (`b"PK\x03\x04"`) **and** attempts to open the bytes with
  `python-docx` (`DocxDocument(BytesIO(content))`), rejecting with 400 on
  any exception — this is a much stronger validity check than magic bytes
  alone (zip signature alone doesn't distinguish docx from xlsx/pptx/odt).
- Replace the hardcoded `filename = f"resume_{timestamp}.pdf"` (line ~153)
  with the extension resolved from the allowlist dict for the validated
  content type.
- Error messages/log lines updated to say "PDF or DOCX" instead of "PDF".

**`pyproject.toml`**

- Add `python-docx>=1.1.0` next to the existing `pdf2image`/`pypdf` entries.

**Tests**

- `tests/test_cv_routes.py`: mirror existing PDF cases for docx — valid
  docx upload (build minimal in-memory docx via `python-docx` in the test,
  as bytes), invalid content-type still rejected, docx with valid MIME/zip
  signature but corrupt internal structure rejected (exercises the new
  `DocxDocument(...)` open-attempt check).
- New test module (or extend `tests/tools/test_vectordb_cv_detection.py`):
  cover `_docx_to_markdown` (headings/paragraphs/tables produce expected
  Markdown) and `_detect_if_cv_from_text` (mocked LLM, is_cv True/False →
  raises/doesn't raise), following the existing mocking patterns in that
  file.

### Frontend changes

Both upload widgets currently duplicate the same PDF-only checks
independently — since this change has to touch both anyway, pull the
allowed-extensions/MIME list and shared copy string into one small constant
(e.g. `frontend/lib/cv-upload.ts`) that both import, so there's a single
source of truth going forward instead of two places that can drift.

- `frontend/app/dashboard/cv/page.tsx`:
  - `uploadFile` MIME check (line 51) → accept both
    `application/pdf` and the docx MIME type; error message → "Only PDF or
    DOCX files are accepted."
  - `<input accept=".pdf" .../>` (line 135) → `accept=".pdf,.docx"`.
  - Copy at lines 104-106 and 129 → mention DOCX ("Upload your CV as a PDF
    or DOCX...", ".pdf, .docx · max 10 MB").
- `frontend/app/dashboard/page.tsx` (`useCvUpload`/`CvUploadPanel`):
  - Same MIME check duplicated at line 79, `accept=".pdf"` at line 217,
    copy at lines 190 and 555 — same updates as above.
  - Fallback filename defaults (`"resume.pdf"` at lines 63 and 68, used only
    when the backend hasn't returned a filename yet) → generic `"resume"`
    since the extension is no longer guaranteed to be `.pdf`.
- `frontend/tests/e2e/user-data-isolation.spec.ts:117` — the assertion
  `page.getByText(/drop your pdf here/i)` is coupled to the exact copy
  string; update it to match whatever the new neutral copy becomes (e.g.
  `/drop your cv here/i`).

### Out of scope (explicitly)

- Legacy `.doc` (binary OLE format) — no viable pure-Python parser exists;
  would require LibreOffice/antiword, rejected per the decision above.
- Refactoring the two upload widgets into one shared component — only the
  small constants file described above is in scope; a full component merge
  is a separate concern not required by this change.

### Verification

1. `uv run pytest tests/test_cv_routes.py tests/tools/ -v` — new and
   existing tests green.
2. `uv run mypy src/` — type-check the new `python-docx` usage (it ships
   type stubs; verify `mypy` is satisfied or add a `types-python-docx` dev
   dependency if needed).
3. Manual end-to-end: start the backend + frontend
   (`docker-compose.dev.yml` or local `uv run`/`npm run dev`), upload a real
   `.docx` CV through `/dashboard/cv`, confirm it reaches `ingestion_status:
   completed`, and confirm job matching still retrieves sensible CV context
   afterward (i.e. the orchestrator's RAG lookup returns non-empty results).
4. Re-upload a PDF CV through the same UI to confirm the existing PDF path
   is unaffected by the dispatch change.
