"""Integration tests for POST /api/upload_cv — DOCX support.

Exercises the real HTTP → FastAPI route → real test-DB session path (via
async_client_a / real_session fixtures from conftest.py). External LLM/vision
clients and the background-ingestion session factory are mocked so the test
never calls a real model or touches the production database — only the
synchronous request-handling path (validation, file write, CVFile row
creation) is asserted against the real test DB.
"""

from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from docx import Document as DocxDocument
from sqlalchemy import select

from src.db.models import CVFile, User

DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def _build_docx_bytes() -> bytes:
    doc = DocxDocument()
    doc.add_paragraph("Real integration-test CV content.")
    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _mock_ingestion_stack() -> tuple:
    """Patch the LLM clients and background-task session factory so the
    request handler's synchronous DB write is exercised for real, but the
    fire-and-forget background ingestion never calls an external model or a
    real (uninitialized-under-ASGITransport) production session factory.
    """
    mock_session_cm = AsyncMock()
    mock_session_cm.__aenter__.return_value = AsyncMock(
        get=AsyncMock(return_value=None)
    )
    mock_session_cm.__aexit__.return_value = False
    mock_factory = MagicMock(return_value=mock_session_cm)

    return (
        patch("src.api.routes.cv.ChatOpenAI"),
        patch("src.api.routes.cv.OpenAIEmbeddings"),
        patch("src.api.routes.cv.CVVectorManager"),
        patch("src.api.routes.cv.get_session_factory", return_value=mock_factory),
    )


@pytest.mark.asyncio
async def test_upload_valid_docx_persists_cv_file_row_with_docx_extension(
    async_client_a, real_session, user_a: User
) -> None:
    """POST /api/upload_cv with a real .docx: 202 response, and the CVFile
    row landed in the real test DB with a .docx-suffixed file_path — proving
    the extension-aware filename fix (Phase 2) end-to-end against the DB,
    not just the response body.
    """
    content = _build_docx_bytes()
    patches = _mock_ingestion_stack()
    with patches[0], patches[1], patches[2], patches[3]:
        response = await async_client_a.post(
            "/api/upload_cv",
            files={"file": ("resume.docx", content, DOCX_CONTENT_TYPE)},
        )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "processing"
    assert body["file_path"].endswith(".docx")

    user_id = user_a.id  # type: ignore[attr-defined]
    result = await real_session.execute(select(CVFile).where(CVFile.user_id == user_id))
    cv_file = result.scalar_one()
    assert str(cv_file.file_path).endswith(".docx")
    assert cv_file.file_hash == body["file_hash"]


@pytest.mark.asyncio
async def test_upload_oversized_docx_rejected_no_cv_file_row_created(
    async_client_a, real_session, user_a: User
) -> None:
    """An oversized DOCX-typed upload is rejected (400) before any CVFile row
    is created — proving the size gate (review fix F1) runs ahead of both
    DOCX parsing and persistence in the real request path.
    """
    oversized_garbage = b"not a valid docx" * (10 * 1024 * 1024)
    response = await async_client_a.post(
        "/api/upload_cv",
        files={"file": ("resume.docx", oversized_garbage, DOCX_CONTENT_TYPE)},
    )

    assert response.status_code == 400
    assert "large" in response.json()["detail"].lower()

    user_id = user_a.id  # type: ignore[attr-defined]
    result = await real_session.execute(select(CVFile).where(CVFile.user_id == user_id))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_upload_corrupt_docx_rejected_no_cv_file_row_created(
    async_client_a, real_session, user_a: User
) -> None:
    """A DOCX-typed upload with a valid zip signature but corrupt internal
    structure is rejected (400) and no CVFile row is created.
    """
    corrupt_content = b"PK\x03\x04" + b"not a real docx internal structure"
    response = await async_client_a.post(
        "/api/upload_cv",
        files={"file": ("resume.docx", corrupt_content, DOCX_CONTENT_TYPE)},
    )

    assert response.status_code == 400
    assert "invalid" in response.json()["detail"].lower()

    user_id = user_a.id  # type: ignore[attr-defined]
    result = await real_session.execute(select(CVFile).where(CVFile.user_id == user_id))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_upload_valid_pdf_still_persists_cv_file_row_with_pdf_extension(
    async_client_a, real_session, user_a: User
) -> None:
    """Regression check: PDF upload is unaffected by the DOCX dispatch — the
    CVFile row still lands with a .pdf-suffixed file_path.
    """
    content = b"%PDF-1.4 integration test content"
    patches = _mock_ingestion_stack()
    with patches[0], patches[1], patches[2], patches[3]:
        response = await async_client_a.post(
            "/api/upload_cv",
            files={"file": ("resume.pdf", content, "application/pdf")},
        )

    assert response.status_code == 202
    body = response.json()
    assert body["file_path"].endswith(".pdf")

    user_id = user_a.id  # type: ignore[attr-defined]
    result = await real_session.execute(select(CVFile).where(CVFile.user_id == user_id))
    cv_file = result.scalar_one()
    assert str(cv_file.file_path).endswith(".pdf")
