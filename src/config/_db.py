from pydantic import BaseModel, Field, SecretStr


class DatabaseMixin(BaseModel):
    """PostgreSQL connection, pgvector dimensions, and RAG chunking parameters."""

    # Dev-only default — MUST be overridden via AGENTIC_HIRE_DATABASE_URL in non-dev envs.
    database_url: SecretStr = Field(
        default=SecretStr(
            "postgresql+asyncpg://agentic_hire:dev_password@localhost:5432/agentic_hire"
        ),
        description="PostgreSQL connection string with asyncpg driver.",
    )
    embedding_dimension: int = Field(
        1536,
        description="Vector embedding dimension for pgvector (default: OpenRouter embeddings).",
    )
    postgres_version: str = Field(
        "17", description="PostgreSQL version (informational)."
    )
    rag_chunk_size: int = Field(
        700, description="Target character size for CV text chunks."
    )
    rag_chunk_overlap: int = Field(
        50, description="Overlap in characters between adjacent CV chunks."
    )
    rag_experience_chunk_threshold: int = Field(
        900,
        description="Experience entries longer than this are sub-split into smaller chunks.",
    )
