<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: DOCX CV Upload Support Implementation Plan

- **Plan**: context/changes/docx-cv-upload-support/plan.md
- **Scope**: Full plan (Phases 1-3)
- **Date**: 2026-07-09
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical, 1 warning, 2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | PASS |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS |

## Findings

### F1 — File-size check runs after the expensive DOCX parse

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: src/api/routes/cv.py:141-158
- **Detail**: `content = await file.read()` reads the full upload into memory with no size cap yet (line 134). For `.docx`, `DocxDocument(BytesIO(content))` (line 152) — which unzips and parses XML — runs before the `len(content) > MAX_FILE_SIZE` check (line 158). A small, highly compressed malicious `.docx` (valid zip signature, tiny compressed size, huge decompressed XML) gets fully unzipped and parsed before any size gate fires. This ordering already existed for PDF (magic-byte check before size check pre-dates this change), but PDF's check is O(1); the new DOCX branch adds a real decompress+parse before the gate, a materially larger amplification of the same pre-existing ordering issue. Blast radius is limited (upload requires auth), so this is resource-exhaustion-shaped, not RCE.
- **Fix**: Move the `len(content) > MAX_FILE_SIZE` check to immediately after `content = await file.read()` (before the empty-file check, line 135), so oversized payloads are rejected before any type-specific parsing — PDF or DOCX.
- **Decision**: FIXED

### F2 — Broad `except Exception:` in DOCX structural validation

- **Severity**: 👁️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: src/api/routes/cv.py:149-157
- **Detail**: Catches bare `except Exception:` around the zip-signature check and `DocxDocument(...)` parse, with no log line. This is validating attacker-controlled bytes at a system boundary (not an external service call), so lessons.md's "Exception Handling" rule doesn't strictly apply — but it still swallows unexpected bugs (e.g. a future python-docx API change) silently as "invalid file," and `PackageNotFoundError` is already imported and used narrowly in vectordb.py:244-247 but not reused here.
- **Fix**: Narrow to `except (ValueError, PackageNotFoundError, BadZipFile)` and add a `logger.debug`/`warning` line inside the except, for parity with this file's other exception handlers.
- **Decision**: FIXED

### F3 — Undocumented 2000-char truncation budget

- **Severity**: 👁️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: src/tools/vectordb.py:179
- **Detail**: `_detect_if_cv_from_text` truncates to `text[:2000]` with no comment explaining the budget. Not a bug — just an unexplained magic number next to `_detect_if_cv`'s vision counterpart, which has no analogous truncation.
- **Fix**: Add a one-line comment noting this mirrors the vision path's implicit token budget for the detection call.
- **Decision**: FIXED
