"""CV upload and management endpoints."""

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from loguru import logger
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user
from src.api.schemas import UploadCVResponse
from src.config.settings import config
from src.db import User, CVFile
from src.db.repositories import CVEmbeddingRepository, CVFileRepository
from src.tools.vectordb import CVVectorManager

router = APIRouter(prefix="/api", tags=["cv"])

CV_UPLOAD_DIR = "data/cv"
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


async def calculate_file_hash(content: bytes) -> str:
    """Calculate SHA256 hash of file content."""
    sha256_hash = hashlib.sha256()
    sha256_hash.update(content)
    return sha256_hash.hexdigest()


@router.post("/upload_cv", response_model=UploadCVResponse)
async def upload_cv(
    file: UploadFile = File(...),
    replace_existing: bool = True,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Upload a CV file and trigger embedding pipeline.

    Args:
        file: PDF file to upload
        replace_existing: If True, delete prior CV files + embeddings for user
        user: Authenticated user (from JWT token)
        db: Database session

    Returns:
        UploadCVResponse with file_id, path, hash, chunks_stored

    Raises:
        HTTPException: 400 for invalid file, 401 for auth failure
    """
    # Validate file type
    if file.content_type != "application/pdf":
        logger.warning(f"Upload attempt with invalid file type: {file.content_type}")
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Only PDF files are allowed.",
        )

    # Read and validate file size
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="File is empty")
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
    filename = f"resume_{timestamp}.pdf"
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

    # Trigger Vision LLM OCR + embedding pipeline
    try:
        # Initialize vision model and embeddings
        api_key_value = config.openrouter_api_key
        api_key: SecretStr | None = SecretStr(api_key_value) if api_key_value else None

        vision_model = ChatOpenAI(
            model=config.vision_model_name,
            temperature=0,
            base_url=config.openrouter_base_url,
            api_key=api_key,
        )

        embeddings = OpenAIEmbeddings(
            model=config.embedded_model_name,
            base_url=config.openrouter_base_url,
            api_key=api_key,
        )

        vector_manager = CVVectorManager(
            vision_model=vision_model,
            embeddings=embeddings,
            user_id=user_id_val,
            cv_cache_dir=str(user_cv_dir),
        )
        result = await vector_manager.ingest_cv_async(str(filepath))
        chunks_stored = result.get("chunks_stored", 0)
        logger.info(
            f"CV ingestion completed for user {user_id_val}: {chunks_stored} chunks"
        )
    except Exception as e:
        logger.error(f"Error ingesting CV: {e}", exc_info=e)
        raise HTTPException(status_code=500, detail="Error processing CV file")

    # Commit transaction
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"Error committing transaction: {e}", exc_info=e)
        raise HTTPException(status_code=500, detail="Error storing file")

    return {
        "file_id": str(cv_file.id),
        "file_path": str(filepath),
        "file_hash": file_hash,
        "chunks_stored": chunks_stored,
        "status": "success",
    }
