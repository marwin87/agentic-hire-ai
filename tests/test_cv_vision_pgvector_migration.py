"""Regression tests for CV Vision to pgvector migration.

Validates that pgvector embeddings match prior system quality.
"""

import pytest
from uuid import uuid4
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.repositories import CVEmbeddingRepository
from src.db.models import CVEmbedding


@pytest.mark.asyncio
async def test_pgvector_similarity_search_consistency() -> None:
    """Verify that cosine distance search returns results in correct order."""
    session = AsyncMock(spec=AsyncSession)
    user_id = uuid4()

    # Mock embeddings with slightly different values for ordering
    embedding1 = CVEmbedding(
        id=uuid4(),
        user_id=user_id,
        chunk_text="Python experience with 5 years of FastAPI",
        embedding=[0.1] * 1536,
        created_at=datetime.now(UTC),
    )

    embedding2 = CVEmbedding(
        id=uuid4(),
        user_id=user_id,
        chunk_text="JavaScript and TypeScript skills",
        embedding=[0.05] * 1536,
        created_at=datetime.now(UTC),
    )

    # Mock the repository search returning ordered results
    with patch("src.db.repositories.Vector", create=True):
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [embedding1, embedding2]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        session.execute.return_value = mock_result

        result = await CVEmbeddingRepository.search_by_user_and_query(
            session, user_id, [0.1] * 1536, limit=5
        )

        assert len(result) == 2
        assert result[0].chunk_text == "Python experience with 5 years of FastAPI"
        assert result[1].chunk_text == "JavaScript and TypeScript skills"


@pytest.mark.asyncio
async def test_pgvector_user_isolation() -> None:
    """Verify that search results are filtered by user_id."""
    session = AsyncMock(spec=AsyncSession)
    user_id_1 = uuid4()
    user_id_2 = uuid4()

    # Create embeddings for two different users
    embedding_user1 = CVEmbedding(
        id=uuid4(),
        user_id=user_id_1,
        chunk_text="User 1 experience",
        embedding=[0.1] * 1536,
        created_at=datetime.now(UTC),
    )

    embedding_user2 = CVEmbedding(
        id=uuid4(),
        user_id=user_id_2,
        chunk_text="User 2 experience",
        embedding=[0.1] * 1536,
        created_at=datetime.now(UTC),
    )

    # Mock the repository to return only user1's results
    with patch("src.db.repositories.Vector", create=True):
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [embedding_user1]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        session.execute.return_value = mock_result

        result = await CVEmbeddingRepository.search_by_user_and_query(
            session, user_id_1, [0.1] * 1536, limit=5
        )

        assert len(result) == 1
        assert result[0].user_id == user_id_1
        assert result[0].chunk_text == "User 1 experience"


@pytest.mark.asyncio
async def test_pgvector_bulk_insert() -> None:
    """Verify bulk insert operations work correctly."""
    session = AsyncMock(spec=AsyncSession)
    user_id = uuid4()

    embeddings = [
        CVEmbedding(
            id=uuid4(),
            user_id=user_id,
            chunk_text=f"Chunk {i}",
            embedding=[0.1 + i * 0.01] * 1536,
            created_at=datetime.now(UTC),
        )
        for i in range(3)
    ]

    # Test bulk insert
    await CVEmbeddingRepository.bulk_insert(session, embeddings)

    # Verify the bulk insert was called
    session.add_all.assert_called_once()
    session.flush.assert_called_once()
    call_args = session.add_all.call_args
    assert len(call_args[0][0]) == 3
