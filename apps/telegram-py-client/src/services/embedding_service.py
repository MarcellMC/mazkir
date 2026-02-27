"""Embedding service using Ollama."""
import logging

from langchain_ollama import OllamaEmbeddings

from src.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Service for generating embeddings using Ollama."""

    def __init__(self):
        """Initialize embedding service."""
        self.embeddings = OllamaEmbeddings(
            model=settings.ollama_embedding_model,
            base_url=settings.ollama_base_url,
        )

    async def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        try:
            # OllamaEmbeddings uses sync by default, wrap in async
            embedding = await self.embeddings.aembed_query(text)
            return embedding
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            raise

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        try:
            embeddings = await self.embeddings.aembed_documents(texts)
            return embeddings
        except Exception as e:
            logger.error(f"Error generating embeddings: {e}")
            raise
