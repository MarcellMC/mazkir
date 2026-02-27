"""Application configuration."""
import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Telegram
    telegram_api_id: int
    telegram_api_hash: str
    telegram_phone: str  # Kept for backwards compatibility, not used in bot mode
    telegram_session_name: str = "mazkir_session"
    telegram_bot_token: str  # Required for bot mode

    # Database
    database_url: str

    # LLM (kept for flexibility)
    anthropic_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    ollama_embedding_model: str = "nomic-embed-text"

    # Claude API
    claude_model: str = "claude-sonnet-4-20250514"
    claude_max_tokens: int = 4000

    # Vault
    vault_path: Path = Path(os.getenv('VAULT_PATH', '/home/marcellmc/pkm'))
    vault_timezone: str = os.getenv('VAULT_TIMEZONE', 'Asia/Jerusalem')

    # Google Calendar integration
    google_credentials_path: Path = Path(os.getenv('GOOGLE_CREDENTIALS_PATH', 'google_credentials.json'))
    google_token_path: Path = Path(os.getenv('GOOGLE_TOKEN_PATH', os.path.expanduser('~/.config/mazkir/google_token.json')))
    google_calendar_id: str | None = os.getenv('GOOGLE_CALENDAR_ID')  # Cached Mazkir calendar ID
    enable_calendar_sync: bool = os.getenv('ENABLE_CALENDAR_SYNC', 'false').lower() == 'true'
    default_habit_time: str = os.getenv('DEFAULT_HABIT_TIME', '07:00')  # Default time for habit events
    default_event_duration: int = int(os.getenv('DEFAULT_EVENT_DURATION', '30'))  # Duration in minutes

    # Features
    enable_webapp: bool = os.getenv('ENABLE_WEBAPP', 'true').lower() == 'true'
    enable_notifications: bool = os.getenv('ENABLE_NOTIFICATIONS', 'true').lower() == 'true'
    debug: bool = os.getenv('DEBUG', 'false').lower() == 'true'

    # Authorized users (for now, just Marc)
    authorized_user_id: int = int(os.getenv('AUTHORIZED_USER_ID', '0'))

    # Application
    log_level: str = "INFO"
    environment: str = "development"

    def validate_config(self):
        """Validate required configuration"""
        assert self.telegram_api_id, "TELEGRAM_API_ID required"
        assert self.telegram_api_hash, "TELEGRAM_API_HASH required"
        assert self.telegram_bot_token, "TELEGRAM_BOT_TOKEN required"
        assert self.anthropic_api_key, "ANTHROPIC_API_KEY required"
        assert self.vault_path.exists(), f"Vault not found at {self.vault_path}"
        assert self.authorized_user_id > 0, "AUTHORIZED_USER_ID required"


# Global settings instance
settings = Settings()
