"""Message ingestion service - fetch, embed, and store messages."""
import logging
from datetime import datetime
from typing import List, Optional

from telethon.tl.types import Message as TelethonMessage

from src.bot.client import MazkirClient
from src.database.connection import async_session_maker
from src.database.repository import MessageRepository
from src.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


class MessageIngestionService:
    """Service for fetching messages and storing them with embeddings."""

    def __init__(self, client: MazkirClient):
        """Initialize the ingestion service."""
        self.client = client
        self.embedding_service = EmbeddingService()

    async def ingest_saved_messages(
        self, limit: int = 100, batch_size: int = 10
    ) -> dict:
        """
        Fetch messages from Saved Messages, generate embeddings, and store them.

        Args:
            limit: Maximum number of messages to fetch
            batch_size: Number of messages to process in each batch

        Returns:
            dict with statistics about the ingestion
        """
        logger.info(f"Starting ingestion of up to {limit} saved messages")

        # Fetch messages
        messages = await self.client.get_saved_messages(limit=limit)
        logger.info(f"Fetched {len(messages)} messages from Saved Messages")

        stats = {
            "total_fetched": len(messages),
            "new_stored": 0,
            "already_exists": 0,
            "skipped_no_text": 0,
            "errors": 0,
        }

        # Process in batches
        for i in range(0, len(messages), batch_size):
            batch = messages[i : i + batch_size]
            batch_stats = await self._process_batch(batch)

            stats["new_stored"] += batch_stats["new_stored"]
            stats["already_exists"] += batch_stats["already_exists"]
            stats["skipped_no_text"] += batch_stats["skipped_no_text"]
            stats["errors"] += batch_stats["errors"]

            logger.info(
                f"Processed batch {i // batch_size + 1}: "
                f"{batch_stats['new_stored']} stored, "
                f"{batch_stats['already_exists']} existed, "
                f"{batch_stats['skipped_no_text']} skipped"
            )

        logger.info(f"Ingestion complete: {stats}")
        return stats

    async def ingest_channel_messages(
        self, channel_id: int | str, limit: int = 100, batch_size: int = 10
    ) -> dict:
        """
        Fetch messages from a channel, generate embeddings, and store them.

        Args:
            channel_id: Channel identifier
            limit: Maximum number of messages to fetch
            batch_size: Number of messages to process in each batch

        Returns:
            dict with statistics about the ingestion
        """
        logger.info(f"Starting ingestion of up to {limit} messages from channel {channel_id}")

        # Fetch messages
        messages = await self.client.get_channel_messages(channel_id, limit=limit)
        logger.info(f"Fetched {len(messages)} messages from channel {channel_id}")

        stats = {
            "total_fetched": len(messages),
            "new_stored": 0,
            "already_exists": 0,
            "skipped_no_text": 0,
            "errors": 0,
        }

        # Process in batches
        for i in range(0, len(messages), batch_size):
            batch = messages[i : i + batch_size]
            batch_stats = await self._process_batch(batch)

            stats["new_stored"] += batch_stats["new_stored"]
            stats["already_exists"] += batch_stats["already_exists"]
            stats["skipped_no_text"] += batch_stats["skipped_no_text"]
            stats["errors"] += batch_stats["errors"]

        logger.info(f"Ingestion complete: {stats}")
        return stats

    async def _process_batch(self, messages: List[TelethonMessage]) -> dict:
        """Process a batch of messages: embed and store."""
        stats = {
            "new_stored": 0,
            "already_exists": 0,
            "skipped_no_text": 0,
            "errors": 0,
        }

        # Filter messages with text
        text_messages = [m for m in messages if m.text]
        stats["skipped_no_text"] = len(messages) - len(text_messages)

        if not text_messages:
            return stats

        # Generate embeddings for all texts in batch
        texts = [m.text for m in text_messages]
        try:
            embeddings = await self.embedding_service.embed_texts(texts)
        except Exception as e:
            logger.error(f"Error generating embeddings: {e}")
            stats["errors"] = len(text_messages)
            return stats

        # Store each message with its embedding
        async with async_session_maker() as session:
            repo = MessageRepository(session)

            for message, embedding in zip(text_messages, embeddings):
                try:
                    # Check if message already exists
                    existing = await repo.get_by_telegram_id(message.id)
                    if existing:
                        stats["already_exists"] += 1
                        continue

                    # Store new message
                    await repo.create(
                        telegram_id=message.id,
                        chat_id=message.chat_id or 0,
                        sender_id=message.sender_id,
                        text=message.text,
                        date=message.date,
                        embedding=embedding,
                    )
                    stats["new_stored"] += 1

                except Exception as e:
                    logger.error(
                        f"Error storing message {message.id}: {e}", exc_info=True
                    )
                    stats["errors"] += 1

        return stats
