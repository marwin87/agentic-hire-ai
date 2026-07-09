"""CV upload and management endpoints."""

import hashlib
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from docx import Document as DocxDocument
from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File, Depends
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from loguru import logger
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user
from src.api.schemas import UploadCVResponse, CVStatusResponse
from src.config.settings import config
from src.db import User, CVFile
from src.db.database import get_session_factory
from src.db.repositories import CVEmbeddingRepository, CVFileRepository
from src.tools.vectordb import CVVectorManager

router = APIRouter(prefix="/api", tags=["cv"])

CV_UPLOAD_DIR = "data/cv"
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_CONTENT_TYPES: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}


async def calculate_file_hash(content: bytes) -> str:
    """Calculate SHA256 hash of file content."""
    sha256_hash = hashlib.sha256()
    sha256_hash.update(content)
    return sha256_hash.hexdigest()


async def _ingest_cv_background(
    file_id: UUID,
    filepath: str,
    vector_manager: CVVectorManager,
) -> None:
    """Background task: run Vision LLM ingestion and stamp CVFile on completion."""
    factory = get_session_factory()
    try:
        await vector_manager.ingest_cv_async(filepath)
        async with factory() as session:
            cv_file = await session.get(CVFile, file_id)
            if cv_file:
                cv_file.ingested_at = datetime.now(timezone.utc)  # type: ignore[assignment]
                await session.commit()
        logger.info(f"[CV] Background ingestion completed for file {file_id}")
    except ValueError as e:
        async with factory() as session:
            cv_file = await session.get(CVFile, file_id)
            if cv_file:
                # Intentional: ValueError messages are LLM-generated CV rejection
                # reasons (e.g. "text too short") — user-safe, not secrets.
                # Accepted risk: if future code ever raises ValueError with provider
                # error text embedded, this would leak. See testing-security-gate plan.
                cv_file.ingestion_error = str(e)  # type: ignore[assignment]
                await session.commit()
        logger.warning(f"[CV] Ingestion rejected for file {file_id}: {e}")
    except Exception as e:
        async with factory() as session:
            cv_file = await session.get(CVFile, file_id)
            if cv_file:
                cv_file.ingestion_error = "CV processing failed. Please try again."  # type: ignore[assignment]
                await session.commit()
        logger.error(f"[CV] Ingestion failed for file {file_id}: {e}", exc_info=e)


@router.get("/cv/status", response_model=CVStatusResponse)
async def cv_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return CV upload state and ingestion status for the authenticated user."""
    user_id_val = cast(UUID, user.id)
    cv_file = await CVFileRepository.get_latest_by_user(db, user_id_val)
    if cv_file is None:
        return {
            "has_cv": False,
            "filename": None,
            "ingestion_status": "none",
            "ingestion_error": None,
        }

    filename = Path(cv_file.file_path).name

    if cv_file.ingestion_error is not None:
        ingestion_status = "failed"
    elif cv_file.ingested_at is not None:
        ingestion_status = "completed"
    else:
        ingestion_status = "processing"

    return {
        "has_cv": True,
        "filename": filename,
        "ingestion_status": ingestion_status,
        "ingestion_error": cv_file.ingestion_error,
    }


@router.post("/upload_cv", response_model=UploadCVResponse, status_code=202)
async def upload_cv(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    replace_existing: bool = True,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Upload a CV file and queue the embedding pipeline as a background task.

    Returns 202 immediately. Poll GET /api/cv/status for ingestion_status.

    Raises:
        HTTPException: 400 for invalid file, 401 for auth failure
    """
    # Validate file type
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        logger.warning(f"Upload attempt with invalid file type: {file.content_type}")
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Only PDF and DOCX files are allowed.",
        )

    # Read and validate file size
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="File is empty")
    # Validate content matches the claimed type — content_type is
    # client-supplied and trivially spoofed. PDF: magic bytes. DOCX: zip
    # signature is not enough on its own (shared with xlsx/pptx/odt), so
    # also attempt a structural open with python-docx.
    extension = ALLOWED_CONTENT_TYPES[file.content_type]
    if extension == ".pdf":
        if not content.startswith(b"%PDF"):
            raise HTTPException(
                status_code=400,
                detail="Invalid file. Only PDF and DOCX files are allowed.",
            )
    else:
        try:
            if not content.startswith(b"PK\x03\x04"):
                raise ValueError("not a zip-based Office document")
            DocxDocument(BytesIO(content))
        except Exception:
            raise HTTPException(
                status_code=400,
                detail="Invalid file. Only PDF and DOCX files are allowed.",
            )
    if len(content) > MAX_FILE_SIZE:
        user_id_val = cast(UUID, user.id)
        logger.warning(
            f"Upload attempt with oversized file: {len(content)} bytes from user {user_id_val}"
        )
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE / 1024 / 1024:.0f}MB.",
        )

    # Create user CV directory
    user_id_val = cast(UUID, user.id)
    user_cv_dir = Path(CV_UPLOAD_DIR) / str(user_id_val)
    user_cv_dir.mkdir(parents=True, exist_ok=True)

    # Generate deterministic filename with timestamp
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"resume_{timestamp}{extension}"
    filepath = user_cv_dir / filename

    # Write file to disk
    try:
        filepath.write_bytes(content)
        logger.info(f"CV file saved to {filepath} for user {user_id_val}")
    except Exception as e:
        logger.error(f"Error writing CV file: {e}", exc_info=e)
        raise HTTPException(status_code=500, detail="Error saving file")

    # Calculate file hash
    file_hash = await calculate_file_hash(content)

    # If replace_existing, delete prior CV files and embeddings
    if replace_existing:
        try:
            prior_cv = await CVFileRepository.get_latest_by_user(db, user_id_val)
            if prior_cv:
                # Delete from filesystem
                prior_path = Path(prior_cv.file_path)
                if prior_path.exists():
                    prior_path.unlink()
                    logger.info(f"Deleted prior CV file: {prior_path}")

                # Delete text cache so next ingest re-runs Vision OCR on the new file
                cache_path = user_cv_dir / f"cv_text_{user_id_val}.md"
                if cache_path.exists():
                    cache_path.unlink()
                    logger.info(f"Deleted CV text cache: {cache_path}")

                # Delete from database
                await CVEmbeddingRepository.delete_by_user(db, user_id_val)
                await db.delete(prior_cv)
                await db.flush()
        except Exception as e:
            logger.error(f"Error cleaning prior CV: {e}", exc_info=e)
            # Don't fail upload, just log and continue

    # Store metadata in cv_files table
    try:
        cv_file = CVFile(
            user_id=user_id_val,
            file_path=str(filepath),
            file_hash=file_hash,
        )
        db.add(cv_file)
        await db.flush()
        logger.info(f"CVFile metadata created: {cv_file.id}")
    except Exception as e:
        logger.error(f"Error creating CVFile record: {e}", exc_info=e)
        raise HTTPException(status_code=500, detail="Error storing file metadata")

    # Commit file record before starting background work
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"Error committing CV record: {e}", exc_info=e)
        raise HTTPException(status_code=500, detail="Error storing file metadata")

    # Build vector manager and enqueue ingestion — returns immediately
    api_key: SecretStr | None = config.openrouter_api_key

    vision_model = ChatOpenAI(
        model=config.vision_model_name,
        temperature=0,
        base_url=config.openrouter_base_url,
        api_key=api_key,
    )
    embeddings_model = OpenAIEmbeddings(
        model=config.embedded_model_name,
        base_url=config.openrouter_base_url,
        api_key=api_key,
    )
    vector_manager = CVVectorManager(
        vision_model=vision_model,
        embeddings=embeddings_model,
        user_id=user_id_val,
        cv_cache_dir=str(user_cv_dir),
    )

    background_tasks.add_task(
        _ingest_cv_background,
        cast(UUID, cv_file.id),
        str(filepath),
        vector_manager,
    )
    logger.info(f"[CV] Ingestion queued for file {cv_file.id}")

    return {
        "file_id": str(cv_file.id),
        "file_path": str(filepath),
        "file_hash": file_hash,
        "status": "processing",
    }
