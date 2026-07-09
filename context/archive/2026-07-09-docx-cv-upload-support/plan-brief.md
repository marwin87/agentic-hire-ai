# DOCX CV Upload Support — Plan Brief

> Full plan: `context/changes/docx-cv-upload-support/plan.md`
> Design notes: `context/changes/docx-cv-upload-support/change.md`

## What & Why

CV upload currently accepts PDF only, enforced independently at the frontend,
the upload endpoint, and the ingestion pipeline. This adds `.docx` (modern
Word Open XML) support so users with a Word-format CV don't have to convert
it to PDF themselves first.

## Starting Point

`CVVectorManager.ingest_cv_async` (`src/tools/vectordb.py`) renders PDF pages
to images and runs each through a Vision LLM to produce Markdown text, which
then flows through header-based chunking, embedding, and pgvector storage.
`src/api/routes/cv.py`'s `upload_cv` and two separately-coded frontend
widgets (`frontend/app/dashboard/cv/page.tsx`,
`frontend/app/dashboard/page.tsx`) both hard-enforce PDF-only.

## Desired End State

A user uploads a `.docx` CV through either dashboard widget; it's validated,
its text/headings/tables are extracted directly (no Vision LLM needed), and
it becomes searchable CV context for job matching exactly like a PDF-derived
CV — with no change to PDF upload behavior.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| Format scope | `.docx` only, no legacy `.doc` | No pure-Python `.doc` parser exists; would require LibreOffice/antiword. | Change |
| Conversion strategy | Pure-Python text extraction (`python-docx`), no office-rendering engine | Every DOCX→PDF tool (LibreOffice, `pdfconverter`, `unoconv`, `docx2pdf`) shells out to a real office suite — 400-600MB dependency, unacceptable for this app's size. | Change |
| CV detection for docx | New text-based sibling (`_detect_if_cv_from_text`) of the existing vision-based check | The docx path never produces a page image to feed the existing vision detector. | Plan |
| Table extraction | Flatten to pipe-separated plain-text lines | Simplest; the Markdown splitters aren't table-aware so real Markdown tables risk mid-row splits. | Plan (user-confirmed) |
| Empty/sparse docx handling | Explicit minimum-text-length guard with a clear `ValueError` | Turns a confusing downstream failure (empty chunks) into an actionable error message. | Plan (user-confirmed) |
| Error classification | `python-docx` open/parse failures raise `ValueError` (recoverable), not bare `Exception` | Matches `context/foundation/lessons.md`'s rule and the existing `_ingest_cv_background` ValueError-vs-Exception contract. | Plan (user-confirmed) |
| Frontend duplication | Shared constants file only, not a shared validation function | Both widgets must be touched regardless; a full logic merge is unrelated-refactoring scope creep. | Plan (user-confirmed) |
| Automated E2E coverage | Deferred to a follow-up `/10x-e2e` run | Keeps this plan focused; browser-level docx-upload testing belongs to the project's dedicated risk-based E2E workflow. | Plan (user-confirmed) |

## Scope

**In scope:**
- `.docx` extraction (`python-docx`), text-based CV detection, format
  dispatch in `ingest_cv_async`
- Upload endpoint content-type allowlist + structural validation +
  extension-aware filename
- Both frontend widgets' MIME check, `accept`, and copy
- Unit + integration tests; manual end-to-end verification

**Out of scope:**
- Legacy `.doc`
- Any office-rendering engine
- Shared frontend validation function/hook (constants only)
- Automated Playwright docx-upload test (follow-up `/10x-e2e`)
- Real Markdown table rendering (plain flattened lines instead)

## Architecture / Approach

Two parallel extraction paths converge on the same Markdown `full_text`
string, after which chunking/embedding/pgvector storage is already
format-agnostic and untouched:

```
.pdf  → pdf2image → page images → Vision LLM OCR → Markdown  ┐
.docx → python-docx → paragraph/heading/table walk → Markdown ┴→ chunk → embed → pgvector
```

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Ingestion pipeline (`vectordb.py`) | docx→Markdown extraction, text-based CV detection, format dispatch, error classification | `python-docx` mypy stub gap under strict mode (mitigation documented in plan) |
| 2. Upload endpoint (`cv.py`) | Content-type allowlist, structural docx validation, extension-aware filename | Zip-signature-only check is too weak alone — mitigated by the `DocxDocument(...)` open-attempt |
| 3. Frontend widgets + E2E verification | Shared constants, both widgets updated, copy-coupled e2e assertion fixed, full manual pass | Two independently-coded widgets must both be updated correctly — verified by an explicit regression check on both |

**Prerequisites:** None beyond the existing PDF pipeline (F-04, S-03 in the
roadmap) already being in place.
**Estimated effort:** ~1 session across 3 phases.

## Open Risks & Assumptions

- Assumes `python-docx>=1.1.0` is compatible with mypy strict mode as-is or
  with a single targeted `# type: ignore` — unverified until Phase 1 adds
  the dependency and runs `mypy`.
- Assumes CVs using tables purely for visual layout (not tabular data) will
  still read reasonably as flattened pipe-separated lines; not pixel-tested
  against a wide variety of real-world Word CV templates.

## Success Criteria (Summary)

- A real `.docx` CV uploaded through either widget reaches
  `ingestion_status: completed` and produces retrievable, non-empty CV
  context for job matching.
- PDF upload behavior is unchanged (regression-verified).
- A non-CV `.docx` is rejected with a clear reason, matching the existing
  PDF CV-detection UX.
