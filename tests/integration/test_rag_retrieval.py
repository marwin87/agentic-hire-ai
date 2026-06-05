"""Integration test for Risk #6: RAG context retrieval returns semantically relevant chunks.

Inserts two CVEmbedding rows with orthogonal deterministic vectors into the real
test DB, then queries with a vector identical to the domain-relevant chunk.
Asserts the correct chunk is ranked first — not just that something is returned.

Anti-pattern avoided: asserting only a non-empty list. The test uses limit=1 and
a domain/decoy pair to prove semantic discrimination.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import CVEmbedding, User
from src.db.repositories import CVEmbeddingRepository

_SOFTWARE_CHUNK_TEXT = (
    "Senior Python software engineer with 5 years of backend experience"
)
_COOKING_CHUNK_TEXT = "Expert pastry chef specializing in French cuisine and dessert"

# Orthogonal 1536-dim unit vectors.
# cosine_distance(_SOFTWARE_VECTOR, _SOFTWARE_VECTOR) = 0.0  → most similar
# cosine_distance(_SOFTWARE_VECTOR, _COOKING_VECTOR)  = 1.0  → least similar
_SOFTWARE_VECTOR: list[float] = [1.0] + [0.0] * 1535
_COOKING_VECTOR: list[float] = [0.0, 1.0] + [0.0] * 1534


@pytest.mark.asyncio
async def test_rag_returns_domain_relevant_chunk_over_decoy(
    real_session: AsyncSession,
    user_a: User,
) -> None:
    """pgvector cosine-distance ranking returns the domain-relevant chunk, not the decoy.

    Proves semantic discrimination: the software engineering chunk must rank above
    the cooking decoy when queried with a software-domain vector.
    """
    user_id = user_a.id  # type: ignore[attr-defined]

    software_embedding = CVEmbedding(
        user_id=user_id,
        chunk_text=_SOFTWARE_CHUNK_TEXT,
        embedding=_SOFTWARE_VECTOR,
    )
    cooking_embedding = CVEmbedding(
        user_id=user_id,
        chunk_text=_COOKING_CHUNK_TEXT,
        embedding=_COOKING_VECTOR,
    )
    await CVEmbeddingRepository.bulk_insert(
        real_session, [software_embedding, cooking_embedding]
    )
    await real_session.flush()

    results = await CVEmbeddingRepository.search_by_user_and_query(
        real_session,
        user_id,
        _SOFTWARE_VECTOR,
        limit=1,
    )

    assert len(results) == 1, f"Expected 1 result, got {len(results)}"
    top_chunk = results[0].chunk_text
    assert (
        "software" in top_chunk.lower()
    ), f"Expected software-domain chunk as top result, got: {top_chunk!r}"
    assert (
        "pastry" not in top_chunk.lower()
    ), f"Cooking decoy ranked above software chunk; got: {top_chunk!r}"
