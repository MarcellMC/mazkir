"""Telethon client setup and initialization."""
import logging

from telethon import TelegramClient
from telethon.sessions import StringSession

from src.config import settings

logger = logging.getLogger(__name__)


class MazkirClient:
    """Wrapper for Telethon client."""

    def __init__(self):
        """Initialize the Telegram client."""
        self.client = TelegramClient(
            settings.telegram_session_name,
            settings.telegram_api_id,
            settings.telegram_api_hash,
        )

    async def start(self):
        """Start the client and authenticate."""
        await self.client.start(phone=settings.telegram_phone)
        me = await self.client.get_me()
        logger.info(f"Logged in as {me.first_name} ({me.phone})")

    async def stop(self):
        """Stop the client."""
        await self.client.disconnect()
        logger.info("Client disconnected")

    async def get_saved_messages(self, limit: int = 100):
        """Get messages from Saved Messages."""
        messages = []
        async for message in self.client.iter_messages("me", limit=limit):
            messages.append(message)
        return messages

    async def get_channel_messages(self, channel_id: int | str, limit: int = 100):
        """Get messages from a channel."""
        messages = []
        async for message in self.client.iter_messages(channel_id, limit=limit):
            messages.append(message)
        return messages
