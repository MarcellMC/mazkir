"""TelegramNotifier — sends proactive, out-of-band Telegram messages.

Used only for background notifications (e.g. a coding session finishing)
that don't originate from an interactive bot request/response cycle. The
interactive bot flow (grammY, in apps/telegram-bot) is unaffected — this
is a narrow, separate integration for push-style notifications.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot_token: str | None, base_url: str = "https://api.telegram.org"):
        self.bot_token = bot_token
        self.base_url = base_url
        # Warn now rather than only at send time. Without a token every
        # out-of-band notification is dropped with a single buried log
        # line -- a coding session finished, pushed its branch, and the
        # user was never told, which read as the session hanging.
        if not bot_token:
            logger.warning(
                "TelegramNotifier has no bot token: out-of-band notifications "
                "(coding session completion) will be dropped. Set "
                "TELEGRAM_BOT_TOKEN in vault-server's .env."
            )

    def send_message(self, chat_id: int, text: str) -> None:
        if not self.bot_token:
            logger.warning("TelegramNotifier: no bot token configured, skipping send_message")
            return
        url = f"{self.base_url}/bot{self.bot_token}/sendMessage"
        try:
            response = httpx.post(url, json={"chat_id": chat_id, "text": text}, timeout=10.0)
            response.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("TelegramNotifier.send_message failed: %s", e)
