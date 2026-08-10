from unittest.mock import MagicMock, patch

from src.services.telegram_notifier import TelegramNotifier


def test_send_message_posts_to_bot_api():
    notifier = TelegramNotifier(bot_token="123:abc")

    with patch("src.services.telegram_notifier.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        notifier.send_message(42, "hello")

    mock_post.assert_called_once_with(
        "https://api.telegram.org/bot123:abc/sendMessage",
        json={"chat_id": 42, "text": "hello"},
        timeout=10.0,
    )


def test_send_message_noop_when_token_missing(caplog):
    notifier = TelegramNotifier(bot_token=None)

    with patch("src.services.telegram_notifier.httpx.post") as mock_post:
        notifier.send_message(42, "hello")  # must not raise

    mock_post.assert_not_called()
    assert "no bot token" in caplog.text.lower()


def test_missing_token_warns_at_construction_not_at_send(caplog):
    """A notifier with no token skips silently at send time, so a coding
    session's completion notification vanishes with only a line buried in
    the log. Surfacing it at construction means it is visible at startup,
    before anything depends on it."""
    import logging
    from src.services.telegram_notifier import TelegramNotifier

    with caplog.at_level(logging.WARNING):
        TelegramNotifier(bot_token=None)

    assert any("token" in r.message.lower() for r in caplog.records)


def test_configured_token_warns_about_nothing(caplog):
    import logging
    from src.services.telegram_notifier import TelegramNotifier

    with caplog.at_level(logging.WARNING):
        TelegramNotifier(bot_token="123:abc")

    assert caplog.records == []
