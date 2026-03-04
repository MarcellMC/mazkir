"""Telegram client configuration."""
import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Telegram
    telegram_api_id: int
    telegram_api_hash: str
    telegram_bot_token: str
    telegram_phone: str = ""  # Kept for backwards compatibility

    # Vault Server
    vault_server_url: str = os.getenv("VAULT_SERVER_URL", "http://localhost:8000")
    vault_server_api_key: str = os.getenv("VAULT_SERVER_API_KEY", "")

    # Security
    authorized_user_id: int = int(os.getenv("AUTHORIZED_USER_ID", "0"))

    # Application
    log_level: str = "INFO"

    def validate_config(self):
        assert self.telegram_api_id, "TELEGRAM_API_ID required"
        assert self.telegram_api_hash, "TELEGRAM_API_HASH required"
        assert self.telegram_bot_token, "TELEGRAM_BOT_TOKEN required"
        assert self.authorized_user_id > 0, "AUTHORIZED_USER_ID required"


settings = Settings()
