import os
import base64
import hashlib
import re
import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from typing import List, Dict, Any, Optional, cast
from uuid import UUID

# OS Dependencies Check
try:
    from pdf2image import convert_from_path
    from PIL import Image
except ImportError:
    print("❌ ERROR: Missing dependencies. Run: pip install pdf2image pillow")
    raise

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.documents import Document
from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
    MarkdownHeaderTextSplitter,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.repositories import CVEmbeddingRepository, CVFileRepository
from src.db.models import CVEmbedding
from src.db.database import get_session_factory


class CVVectorManager:
    """
    Manages CV ingestion and retrieval using pgvector backend.
    Vision pipeline: PDF → Vision LLM OCR → chunks → embeddings → pgvector.
    """

    def __init__(
        self,
        vision_model: Any,
        embeddings: Any,
        user_id: UUID,
        cv_cache_dir: str = "data/cv",
    ) -> None:
        self.vision_model = vision_model
        self.embeddings = embeddings  # type: ignore
        self.user_id = user_id
        self.cv_cache_dir = cv_cache_dir
        os.makedirs(self.cv_cache_dir, exist_ok=True)

        # Cache files stored locally for Vision LLM output (text fallback)
        self.cv_text_cache_path = os.path.join(
            self.cv_cache_dir, f"cv_text_{user_id}.md"
        )

    def _run_async(self, coro: Any) -> Any:
        """Run an async coroutine from sync context (thread-safe)."""
        runner = asyncio.Runner()
        try:
            return runner.run(coro)
        finally:
            runner.close()


    @staticmethod
    def _calculate_file_hash(file_path: str) -> str:
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    @staticmethod
    def _pdf_to_base64_images(file_path: str) -> List[str]:
        images = convert_from_path(file_path, dpi=150)
        base64_images = []

        for img in images:
            buffered = BytesIO()
            img.save(buffered, format="JPEG", quality=85)
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            base64_images.append(img_str)

        return base64_images

    @staticmethod
    def _normalize_bullets(text: str) -> str:
        return re.sub(r"[•\-\*]", "\n•", text)

    def _process_single_page(self, page_data: tuple) -> str:
        i, b64_img, total = page_data
        print(f"Processing page {i + 1}/{total}")

        system_msg = SystemMessage(
            content="You are an expert recruitment assistant specializing in CV transcription."
        )
        human_msg = HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": (
                        "Transcribe the CV page in Markdown.\n"
                        "# for name\n"
                        "## for sections (Experience, Education, Skills)\n"
                        "### for entries (jobs, degrees)"
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{b64_img}",
                        "detail": "high",
                    },
                },
            ]
        )
        response = self.vision_model.invoke([system_msg, human_msg])
        content = response.content
        if isinstance(content, str):
            return content
        return str(content)

    @staticmethod
    def _split_experience_block(text: str) -> List[str]:
        """
        Splits experience section into job-level chunks using ### headers.
        """
        jobs = re.split(r"\n(?=### )", text)
        return [job.strip() for job in jobs if job.strip()]

    async def ingest_cv_async(self, file_path: str) -> Dict[str, Any]:
        """Async version of CV ingestion that stores to pgvector."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Resume not found at: {file_path}")

        new_hash = self._calculate_file_hash(file_path)

        # Check if file hash is cached and embeddings exist in pgvector
        if os.path.exists(self.cv_text_cache_path):
            print(
                "✅ CV unchanged. Re-embedding from text cache (skipping Vision LLM)..."
            )
            with open(self.cv_text_cache_path, "r") as f:
                full_text = f.read()
            print(f"✅ Text loaded from cache ({len(full_text)} chars)")
        else:
            print("👁️ Reading CV via Vision model...")
            base64_images = self._pdf_to_base64_images(file_path)
            page_data = [
                (i, img, len(base64_images)) for i, img in enumerate(base64_images)
            ]

            with ThreadPoolExecutor() as executor:
                clean_text_parts = list(
                    executor.map(self._process_single_page, page_data)
                )

            full_text = "\n\n".join(clean_text_parts)
            full_text = self._normalize_bullets(full_text)

            with open(self.cv_text_cache_path, "w") as f:
                f.write(full_text)

            print(f"✅ Text reconstructed ({len(full_text)} chars)")

        # --- Markdown Header Split ---
        headers_to_split_on = [
            ("#", "Header 1"),
            ("##", "Header 2"),
            ("###", "Header 3"),
        ]

        markdown_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=headers_to_split_on,
            strip_headers=False,
        )

        md_docs = markdown_splitter.split_text(full_text)

        # --- Improved Recursive Splitter ---
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=700,
            chunk_overlap=50,
            separators=["\n\n", "\n", "•", ". "],
        )

        final_chunks: List[Document] = []

        for doc in md_docs:
            section = (doc.metadata.get("Header 2") or "").lower()

            # --- EXPERIENCE: custom job-level splitting ---
            if "experience" in section:
                jobs = self._split_experience_block(doc.page_content)

                for job in jobs:
                    if len(job) > 900:
                        sub_chunks = text_splitter.split_text(job)
                        for chunk in sub_chunks:
                            final_chunks.append(
                                Document(
                                    page_content=chunk,
                                    metadata={**doc.metadata, "section": "experience"},
                                )
                            )
                    else:
                        final_chunks.append(
                            Document(
                                page_content=job,
                                metadata={**doc.metadata, "section": "experience"},
                            )
                        )

            # --- OTHER SECTIONS ---
            else:
                chunks = text_splitter.split_text(doc.page_content)

                for chunk in chunks:
                    final_chunks.append(
                        Document(
                            page_content=chunk,
                            metadata={
                                **doc.metadata,
                                "section": section or "general",
                            },
                        )
                    )

        if not final_chunks:
            raise RuntimeError("No chunks generated from CV.")

        # --- Generate embeddings and store in pgvector ---
        factory = get_session_factory()
        async with factory() as session:
            # Delete existing embeddings for this user
            await CVEmbeddingRepository.delete_by_user(session, self.user_id)

            # Create CVEmbedding objects with embeddings
            embeddings_list: List[CVEmbedding] = []
            for chunk in final_chunks:
                embedding_vector = self.embeddings.embed_query(chunk.page_content)
                cv_embedding = CVEmbedding(
                    user_id=self.user_id,
                    chunk_text=chunk.page_content,
                    embedding=embedding_vector,
                )
                embeddings_list.append(cv_embedding)

            # Bulk insert into pgvector
            await CVEmbeddingRepository.bulk_insert(session, embeddings_list)
            await session.commit()

        print(f"✅ Stored {len(final_chunks)} structured chunks in pgvector.")
        return {
            "status": "success",
            "chunks_stored": len(final_chunks),
            "hash": new_hash,
        }

    def ingest_cv(self, file_path: str) -> Dict[str, Any]:
        """Synchronous wrapper for CV ingestion (called via asyncio.to_thread)."""
        return self._run_async(self.ingest_cv_async(file_path))

    async def get_context_async(self, query: str, limit: int = 5) -> str:
        """Retrieve relevant CV chunks from pgvector using semantic search."""
        factory = get_session_factory()
        async with factory() as session:
            # Generate embedding for query
            query_embedding = self.embeddings.embed_query(query)

            # Search pgvector for similar chunks (cosine distance, user-filtered)
            results = await CVEmbeddingRepository.search_by_user_and_query(
                session, self.user_id, query_embedding, limit=limit
            )

            if not results:
                return ""

            context_parts: List[str] = []
            for embedding in results:
                context_parts.append(embedding.chunk_text)

            return "\n---\n".join(context_parts)

    def get_context(self, query: str, limit: int = 5) -> str:
        """Synchronous wrapper for context retrieval (called via asyncio.to_thread)."""
        return self._run_async(self.get_context_async(query, limit))

    async def get_full_resume_text_async(self) -> str:
        """Retrieve all CV chunks for this user from pgvector."""
        from sqlalchemy import select

        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(CVEmbedding)
                .where(CVEmbedding.user_id == self.user_id)
                .order_by(CVEmbedding.created_at)
            )
            embeddings = result.scalars().all()

            if not embeddings:
                raise RuntimeError("No CV embeddings found.")

            chunks = [e.chunk_text for e in embeddings]
            return "\n".join(chunks)

    def get_full_resume_text(self) -> str:
        """Synchronous wrapper to get full resume (called via asyncio.to_thread)."""
        return self._run_async(self.get_full_resume_text_async())
