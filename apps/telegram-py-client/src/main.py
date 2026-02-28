"""Main entry point for Mazkir Telegram client."""
import asyncio
import logging
from telethon import TelegramClient
from src.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    try:
        settings.validate_config()
    except AssertionError as e:
        logger.error(f"Configuration error: {e}")
        return

    logger.info("Starting Mazkir Telegram client...")

    from src.bot.handlers import get_handlers

    client = TelegramClient(
        "mazkir_bot_session",
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )

    handlers = get_handlers()
    for handler_func, event_builder in handlers:
        client.add_event_handler(handler_func, event_builder)

    await client.start(bot_token=settings.telegram_bot_token)

    me = await client.get_me()
    logger.info(f"Bot started: @{me.username}")
    logger.info(f"Vault server: {settings.vault_server_url}")
    logger.info(f"Authorized user: {settings.authorized_user_id}")

    print(f"\nMazkir Telegram client running as @{me.username}")
    print(f"Vault server: {settings.vault_server_url}")
    print("Press Ctrl+C to stop\n")

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
