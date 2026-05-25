---
change_id: user-cv-upload
title: User CV upload and embedding
status: planned
created: 2026-05-25
updated: 2026-05-25
---

# S-03: User CV Upload and Embedding

## Overview

Users can upload a PDF resume via a FastAPI endpoint. The system:
1. Validates the file (PDF, size ≤ 10MB)
2. Stores the PDF to `data/cv/{user_id}/{filename}.pdf`
3. Triggers Vision LLM OCR + embedding pipeline (CVVectorManager.ingest_cv_async)
4. Returns processing status and embedding chunk count

**Design Decision: Q2 Resolved** — CV files stored on filesystem (path recorded in cv_files table), not Postgres bytea.

## Prerequisites Met

- ✅ F-01: FastAPI server with dependencies injection ready
- ✅ F-02: PostgreSQL + pgvector schema (cv_files, cv_embeddings tables exist)
- ✅ F-04: Vision LLM pipeline refactored (CVVectorManager.ingest_cv_async() ready to call)

## What We're NOT Doing

- UI drag-drop form (Phase 2)
- Async job queue for background processing (Phase 2)
- Multiple CV versions per user (MVP: single active CV per user)
- Webhook notifications on completion (Phase 2)
- File storage encryption (Phase 2)

## Phase 1: Endpoint & File Handling

### Overview

Create POST `/upload_cv` endpoint that validates, stores, and queues CV for embedding.

### Changes Required

1. **Create CVUploadRequest schema** (`src/api/schemas.py`)
   - `file: UploadFile` (Pydantic FileUpload)
   - `replace_existing: bool = True` (overwrite prior CV or error if exists)

2. **Create UploadCVResponse schema** (`src/api/schemas.py`)
   - `file_id: str` (CVFile.id UUID)
   - `file_path: str` (relative path where stored)
   - `file_hash: str` (SHA256 of file)
   - `chunks_stored: int` (count of embeddings created)
   - `status: str` ("success" or error code)

3. **Add upload endpoint** (`src/api/routes/validation.py` or new `src/api/routes/cv.py`)
   - POST `/upload_cv` requiring auth (Depends(get_current_user))
   - Accept multipart form with `file` field
   - Validate: PDF only, ≤ 10MB, non-empty
   - Create `data/cv/{user_id}/` directory if missing
   - Save file with deterministic name: `resume_{timestamp}.pdf`
   - Calculate file hash (SHA256)
   - If replace_existing=True, delete prior cv_files + cv_embeddings for user
   - Call CVVectorManager(user_id).ingest_cv_async(filepath)
   - Store metadata in cv_files table
   - Return UploadCVResponse with chunk count

4. **Register endpoint in main.py**
   - Include router in app.include_router()

### Success Criteria: Automated

- [ ] 1.1 POST `/upload_cv` accepts PDF file from authenticated user
- [ ] 1.2 Rejects non-PDF files with 400 + "Invalid file type"
- [ ] 1.3 Rejects files > 10MB with 400 + "File too large"
- [ ] 1.4 File stored to `data/cv/{user_id}/resume_{timestamp}.pdf`
- [ ] 1.5 SHA256 hash calculated and stored in cv_files
- [ ] 1.6 CVVectorManager.ingest_cv_async() called and completes
- [ ] 1.7 Response includes chunks_stored count > 0
- [ ] 1.8 Unauthenticated request returns 401

### Success Criteria: Manual

- [ ] 1.M1 Upload a sample CV via `/upload_cv` and confirm file saved to filesystem
- [ ] 1.M2 Confirm cv_files table has one row with correct metadata
- [ ] 1.M3 Confirm cv_embeddings table has multiple rows for chunks
- [ ] 1.M4 Upload same user's CV again with replace_existing=True and confirm prior embeddings deleted
- [ ] 1.M5 Try uploading a non-PDF file and confirm 400 error

---

## Phase 2: Frontend Upload Form

### Overview

Add UI component to dashboard for CV upload with drag-drop support and progress feedback.

### Changes Required

1. **Update dashboard.html** (`ui/dashboard.html`)
   - Add file upload form with drag-drop target
   - Accept .pdf files only
   - Show file size and validation feedback
   - Progress bar during upload (polling /upload_cv)
   - Display embedding status: "Uploaded X chunks"

2. **Add JavaScript handlers** (`ui/dashboard.html`)
   - ondrop/ondragover for drag-drop
   - File type/size validation client-side
   - POST /upload_cv with multipart FormData
   - Poll response for chunks_stored count
   - Error banner on upload failure

### Success Criteria: Automated

- [ ] 2.1 Dashboard HTML loads with upload form visible
- [ ] 2.2 Form accepts only .pdf files (input accept attribute)
- [ ] 2.3 Size validation rejects > 10MB before upload

### Success Criteria: Manual

- [ ] 2.M1 Navigate to dashboard and see upload form
- [ ] 2.M2 Drag-drop a PDF file and confirm upload completes
- [ ] 2.M3 Confirm "X chunks stored" message appears after processing
- [ ] 2.M4 Try to upload a .txt file and confirm rejection
- [ ] 2.M5 Try to upload a > 10MB file and confirm rejection

---

## Integration Notes

**CVVectorManager dependencies:**
- Requires config.vision_model_name (default: openai/gpt-4o) — already set
- Requires AGENTIC_HIRE_OPENROUTER_API_KEY in .env — already used by other agents
- Creates file at cv_cache_dir (default: data/cv) — we'll set this to same directory for consistency

**Database migrations:**
- No new migrations needed; cv_files and cv_embeddings tables already exist from F-02

**File storage:**
- Directory: `data/cv/{user_id}/` (user_id is UUID, human-readable in paths)
- Naming: `resume_{timestamp}.pdf` (allows multiple versions if needed later; Phase 1 keeps one active)
- Cleanup: on replace_existing=True, delete old file from filesystem + DB records

---

## Progress

### Phase 1: Endpoint & File Handling

#### Automated
- [x] 1.1 POST `/upload_cv` accepts PDF file from authenticated user
- [x] 1.2 Rejects non-PDF files with 400 + "Invalid file type"
- [x] 1.3 Rejects files > 10MB with 400 + "File too large"
- [x] 1.4 File stored to `data/cv/{user_id}/resume_{timestamp}.pdf`
- [x] 1.5 SHA256 hash calculated and stored in cv_files
- [x] 1.6 CVVectorManager.ingest_cv_async() called and completes
- [x] 1.7 Response includes chunks_stored count > 0
- [x] 1.8 Unauthenticated request returns 401

#### Manual
- [x] 1.M1 Upload a sample CV via `/upload_cv` and confirm file saved to filesystem
- [x] 1.M2 Confirm cv_files table has one row with correct metadata
- [x] 1.M3 Confirm cv_embeddings table has multiple rows for chunks
- [x] 1.M4 Upload same user's CV again with replace_existing=True and confirm prior embeddings deleted
- [x] 1.M5 Try uploading a non-PDF file and confirm 400 error

### Phase 2: Frontend Upload Form

#### Automated
- [x] 2.1 Dashboard HTML loads with upload form visible
- [x] 2.2 Form accepts only .pdf files (input accept attribute)
- [x] 2.3 Size validation rejects > 10MB before upload

#### Manual
- [x] 2.M1 Navigate to dashboard and see upload form
- [x] 2.M2 Drag-drop a PDF file and confirm upload completes
- [x] 2.M3 Confirm "X chunks stored" message appears after processing
- [x] 2.M4 Try to upload a .txt file and confirm rejection
- [x] 2.M5 Try to upload a > 10MB file and confirm rejection
